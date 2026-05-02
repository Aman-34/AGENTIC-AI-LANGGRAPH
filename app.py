from __future__ import annotations
import re
from datetime import date
from pathlib import Path
from io import BytesIO
import streamlit as st

from BGP_backend import app, get_all_blogs, get_blog, publish_to_hashnode

# -----------------------------
# HELPERS
# -----------------------------
def safe_slug(title: str) -> str:
    return re.sub(r"\W+", "_", title.lower())

def bundle_zip(md_text: str, filename: str) -> bytes:
    import zipfile
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(filename, md_text)
    return buf.getvalue()

# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="Blog Agent", layout="wide")
st.title(" Hashnode Forge AI  ")

# -----------------------------
# SIDEBAR
# -----------------------------
with st.sidebar:
    topic = st.text_area("Enter Topic")
    run_btn = st.button("Generate")

    st.divider()
    st.subheader("Past Blogs")

    blogs = get_all_blogs()
    blog_map = {f"{b[1]} ({b[3]})": b[0] for b in blogs}

    if blog_map:
        selected = st.selectbox("Select", list(blog_map.keys()))
        if st.button("Load"):
            blog_id = blog_map[selected]
            title, content = get_blog(blog_id)
            st.session_state["out"] = {"plan": {"blog_title": title}, "final": content}

# -----------------------------
# RUN
# -----------------------------
if run_btn and topic:
    inputs = {
        "topic": topic,
        "plan": None,
        "sections": [],
        "final": "",
        "blog_title": "",
        "as_of": date.today().isoformat()
    }

    with st.spinner("Generating..."):
        out = app.invoke(inputs)
        st.session_state["out"] = out

# -----------------------------
# OUTPUT
# -----------------------------
out = st.session_state.get("out")

if out:
    st.subheader("📄 Blog")

    final = out.get("final", "")
    title = out.get("plan").blog_title if hasattr(out.get("plan"), "blog_title") else "blog"

    st.markdown(final)

    filename = safe_slug(title) + ".md"

    st.download_button("Download Markdown", final, file_name=filename)
    st.download_button("Download ZIP", bundle_zip(final, filename), file_name="blog.zip")

    # Publish
    if st.button("🚀 Publish to Hashnode"):
        with st.spinner("Publishing..."):
            result = publish_to_hashnode(title, final)

            if "post_url" in result:
                st.success("✅ Published Successfully!")
                st.write(result["post_url"])
            else:
                st.error("❌ Failed")
                st.write(result.get("error"))
else:
    st.info("Enter topic to generate blog")