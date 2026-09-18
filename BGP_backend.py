from __future__ import annotations
import operator
import sqlite3
from datetime import date
from typing import TypedDict, List, Optional, Annotated
import os
import requests

from pydantic import BaseModel
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv

# ----------------------------
# LOAD ENV
# ----------------------------
import os

# Try Streamlit secrets first
try:
    import streamlit as st
    HASHNODE_TOKEN = st.secrets["HASHNODE_TOKEN"]
    HASHNODE_USERNAME = st.secrets["HASHNODE_USERNAME"]

# Fallback to .env (for local use)
except Exception:
    from dotenv import load_dotenv
    load_dotenv()

    HASHNODE_TOKEN = os.getenv("HASHNODE_TOKEN")
    HASHNODE_USERNAME = os.getenv("HASHNODE_USERNAME")


if not HASHNODE_TOKEN or not HASHNODE_USERNAME:
    raise ValueError("❌ Missing HASHNODE_TOKEN or HASHNODE_USERNAME")
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
    cur.execute("""
        SELECT id, blog_title, topic, created_at
        FROM blogs ORDER BY id DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

def get_blog(blog_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT blog_title, content FROM blogs WHERE id=?
    """, (blog_id,))
    row = cur.fetchone()
    conn.close()
    return row

# ----------------------------
# LLM
# ----------------------------
llm = ChatGroq(
    model= "qwen/qwen3.6-27b",
    temperature=0.8,
    max_tokens=500
)
# ----------------------------
# SCHEMA
# ----------------------------
class Task(BaseModel):
    id: int
    title: str
    goal: str
    bullets: List[str]
    target_words: int

class Plan(BaseModel):
    blog_title: str
    audience: str
    tone: str
    blog_kind: str
    tasks: List[Task]

class State(TypedDict):
    topic: str
    plan: Optional[Plan]
    sections: Annotated[List[tuple[int, str]], operator.add]
    final: str
    blog_title: str
    as_of: str

# ----------------------------
# NODES
# ----------------------------
import json
import re

def extract_json(text: str):
    """Extract JSON from messy LLM output"""
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except:
        pass
    return None


def planner_node(state: State):

    prompt = [
        SystemMessage(content="""
Create a structured blog plan.

IMPORTANT:
Return JSON format.

Example:
{
  "blog_title": "Sample Title",
  "audience": "students",
  "tone": "informative",
  "blog_kind": "educational",
  "tasks": [
    {
      "id": 1,
      "title": "Introduction",
      "goal": "Explain basics",
      "bullets": ["point1", "point2"],
      "target_words": 100
    }
  ]
}
"""),
        HumanMessage(content=state["topic"])
    ]

    response = llm.invoke(prompt)
    content = response.content.strip()

    # -------------------------
    # TRY PARSING JSON
    # -------------------------
    parsed = None

    try:
        parsed = json.loads(content)
    except:
        parsed = extract_json(content)

    # -------------------------
    # FALLBACK (NO CRASH)
    # -------------------------
    if not parsed:
        print("⚠️ Using fallback plan")

        parsed = {
            "blog_title": state["topic"].title(),
            "audience": "general audience",
            "tone": "informative",
            "blog_kind": "blog",
            "tasks": [
                {
                    "id": 1,
                    "title": "Introduction",
                    "goal": "Introduce the topic",
                    "bullets": ["overview", "importance"],
                    "target_words": 120
                },
                {
                    "id": 2,
                    "title": "Main Concepts",
                    "goal": "Explain key ideas",
                    "bullets": ["concept1", "concept2"],
                    "target_words": 200
                },
                {
                    "id": 3,
                    "title": "Conclusion",
                    "goal": "Summarize",
                    "bullets": ["summary", "final thoughts"],
                    "target_words": 100
                }
            ]
        }

    # -------------------------
    # VALIDATE SAFELY
    # -------------------------
    try:
        plan = Plan(**parsed)
    except Exception as e:
        print("⚠️ Schema fix applied:", e)

        # minimal safe plan
        plan = Plan(
            blog_title=state["topic"].title(),
            audience="general",
            tone="informative",
            blog_kind="blog",
            tasks=[
                Task(
                    id=1,
                    title="Overview",
                    goal="Explain topic",
                    bullets=["intro"],
                    target_words=150
                )
            ]
        )

    return {
        "plan": plan,
        "blog_title": plan.blog_title
    }

def fanout(state: State):
    return [Send("worker", {"task": t.model_dump()}) for t in state["plan"].tasks]

def worker(payload):
    task = payload["task"]
    content = llm.invoke([
        SystemMessage(content="Write a detailed blog section"),
        HumanMessage(content=task["title"])
    ]).content
    return {"sections": [(task["id"], content)]}

def reducer(state: State):
    ordered = [s for _, s in sorted(state["sections"])]
    final = "\n\n".join(ordered)

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
g.add_node("worker", worker)
g.add_node("reducer", reducer)

g.add_edge(START, "planner")
g.add_conditional_edges("planner", fanout, ["worker"])
g.add_edge("worker", "reducer")
g.add_edge("reducer", END)

app = g.compile()

# ----------------------------
import requests

import requests

def publish_to_hashnode(title: str, content: str) -> dict:
    url = "https://gql.hashnode.com"

    headers = {
        "Authorization": f"Bearer {HASHNODE_TOKEN.strip()}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    # -----------------------------
    # STEP 1: GET USER + PUBLICATION
    # -----------------------------
    query = """
    query {
      me {
        username
        publications(first: 1) {
          edges {
            node {
              id
              url
            }
          }
        }
      }
    }
    """

    res = requests.post(url, json={"query": query}, headers=headers)

    if res.status_code != 200:
        return {
            "error": "HTTP Error (Step 1)",
            "status_code": res.status_code,
            "response": res.text[:300]
        }

    try:
        data = res.json()
    except Exception:
        return {
            "error": "Invalid JSON response (Step 1)",
            "response": res.text[:300]
        }

    if "errors" in data:
        return {"error": data["errors"]}

    edges = data["data"]["me"]["publications"]["edges"]
    if not edges:
        return {"error": "No publication found"}

    publication_id = edges[0]["node"]["id"]

    # -----------------------------
    # STEP 2: CREATE POST (WORKING MUTATION)
    # -----------------------------
    mutation = """
    mutation CreateStory($input: CreateStoryInput!) {
      createStory(input: $input) {
        post {
          id
          slug
          url
        }
      }
    }
    """

    variables = {
        "input": {
            "title": title,
            "contentMarkdown": content,
            "publicationId": publication_id,
            "tags": []
        }
    }

    res = requests.post(
        url,
        json={"query": mutation, "variables": variables},
        headers=headers
    )

    if res.status_code != 200:
        return {
            "error": "HTTP Error (Step 2)",
            "status_code": res.status_code,
            "response": res.text[:300]
        }

    try:
        result = res.json()
    except Exception:
        return {
            "error": "Invalid JSON response (Step 2)",
            "response": res.text[:300]
        }

    if "errors" in result:
        return {"error": result["errors"]}

    post = result["data"]["createStory"]["post"]

    return {
        "post_url": post["url"],
        "slug": post["slug"],
        "message": "✅ Blog published successfully"
    }