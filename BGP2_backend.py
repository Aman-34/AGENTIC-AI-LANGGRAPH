from __future__ import annotations
import sqlite3
from typing import TypedDict, List, Optional
import os
import time
import requests

import streamlit as st
from dotenv import load_dotenv

from pydantic import BaseModel
from langgraph.graph import StateGraph, START, END
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

# ----------------------------
# LOAD ENV (SAFE)
# ----------------------------
load_dotenv()

def get_secret(key: str):
    val = os.getenv(key)
    if val:
        return val
    try:
        return st.secrets[key]
    except Exception:
        return None

HASHNODE_TOKEN = get_secret("HASHNODE_TOKEN")
HASHNODE_USERNAME = get_secret("HASHNODE_USERNAME")
HASHNODE_PUBLICATION_ID = get_secret("HASHNODE_PUBLICATION_ID")

if not HASHNODE_TOKEN:
    st.warning("⚠️ Hashnode token missing")

# ----------------------------
# DATABASE
# ----------------------------
DB_NAME = "blogs.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS blogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            blog_title TEXT,
            content TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def save_blog(topic, title, content, created_at):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO blogs (topic, blog_title, content, created_at)
        VALUES (?, ?, ?, ?)
    """, (topic, title, content, created_at))
    conn.commit()
    conn.close()

def get_all_blogs():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, blog_title, topic, created_at FROM blogs ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_blog(blog_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT blog_title, content FROM blogs WHERE id=?", (blog_id,))
    row = cur.fetchone()
    conn.close()
    return row

# ----------------------------
# LLM (FIXED)
# ----------------------------
llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0,
    max_tokens=1500,
    timeout=60,
    max_retries=2
)

def safe_invoke(messages):
    for _ in range(3):
        try:
            return llm.invoke(messages)
        except Exception as e:
            if "rate_limit" in str(e).lower():
                time.sleep(6)
            else:
                raise e

# ----------------------------
# SCHEMA
# ----------------------------
class Task(BaseModel):
    id: int
    title: str

class Plan(BaseModel):
    blog_title: str
    tasks: List[Task]

class State(TypedDict):
    topic: str
    plan: Optional[Plan]
    sections: List[str]
    final: str
    blog_title: str
    as_of: str

# ----------------------------
# PLANNER (DYNAMIC)
# ----------------------------
def planner_node(state: State):
    try:
        response = safe_invoke([
            SystemMessage(content="Generate a blog title and 3-4 section headings"),
            HumanMessage(content=state["topic"])
        ])

        lines = response.content.split("\n")
        tasks = []
        idx = 1

        for line in lines:
            clean = line.strip("- ").strip()
            if clean:
                tasks.append(Task(id=idx, title=clean))
                idx += 1

        if not tasks:
            raise Exception("Empty plan")

    except:
        tasks = [
            Task(id=1, title="Introduction"),
            Task(id=2, title="Key Concepts"),
            Task(id=3, title="Conclusion")
        ]

    return {
        "plan": Plan(blog_title=state["topic"].title(), tasks=tasks),
        "blog_title": state["topic"].title()
    }

# ----------------------------
# WORKER (STRONG PROMPT)
# ----------------------------
def worker_node(state: State):
    sections = []

    for task in state["plan"].tasks:
        response = safe_invoke([
            SystemMessage(content="You are a professional blog writer."),
            HumanMessage(
                content=f"""
Write a detailed blog section.

Topic: {state['topic']}
Section: {task.title}

Make it:
- Unique
- Informative
- With examples
- Not generic
"""
            )
        ])
        sections.append(response.content)

    return {"sections": sections}

# ----------------------------
# REDUCER
# ----------------------------
def reducer(state: State):
    final = "\n\n".join(state["sections"])

    save_blog(
        topic=state["topic"],
        title=state["blog_title"],
        content=final,
        created_at=state["as_of"]
    )

    return {"final": final}

# ----------------------------
# GRAPH
# ----------------------------
g = StateGraph(State)

g.add_node("planner", planner_node)
g.add_node("worker", worker_node)
g.add_node("reducer", reducer)

g.add_edge(START, "planner")
g.add_edge("planner", "worker")
g.add_edge("worker", "reducer")
g.add_edge("reducer", END)

app_graph = g.compile()

# ----------------------------
# HASHNODE (REAL PUBLISH)
# ----------------------------
def publish_to_hashnode(title: str, content: str) -> dict:
    if not HASHNODE_TOKEN or not HASHNODE_PUBLICATION_ID:
        return {"error": "Missing Hashnode credentials"}

    url = "https://gql.hashnode.com/"

    query = """
    mutation PublishPost($input: PublishPostInput!) {
      publishPost(input: $input) {
        post {
          url
        }
      }
    }
    """

    variables = {
        "input": {
            "title": title,
            "contentMarkdown": content,
            "publicationId": HASHNODE_PUBLICATION_ID
        }
    }

    headers = {
        "Authorization": HASHNODE_TOKEN,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json={
            "query": query,
            "variables": variables
        }, headers=headers)

        data = response.json()

        if "errors" in data:
            return {"error": data["errors"]}

        post_url = data["data"]["publishPost"]["post"]["url"]

        return {"post_url": post_url}

    except Exception as e:
        return {"error": str(e)}