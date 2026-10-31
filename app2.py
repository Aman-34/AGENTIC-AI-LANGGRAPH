from __future__ import annotations
import re
from datetime import date
from io import BytesIO
import streamlit as st

from BGP2_backend import app_graph, get_all_blogs, get_blog, publish_to_hashnode

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
# UI CONFIG
# -----------------------------
st.set_page_config(page_title="Blog Agent", layout="wide")
st.title("🚀 Hashnode Forge AI")

# -----------------------------
# CLEAR BUTTON (IMPORTANT)
# -----------------------------
if st.button(" Clear Previous Output"):
    st.session_state.clear()
    st.rerun()

# -----------------------------
# SIDEBAR
# -----------------------------
with st.sidebar:
    topic = st.text_area("Enter Topic")
    run_btn = st.button("Generate")

    st.divider()
    st.subheader(" Past Blogs")

    blogs = get_all_blogs()
    blog_map = {f"{b[1]} ({b[3]})": b[0] for b in blogs}

    if blog_map:
        selected = st.selectbox("Select", list(blog_map.keys()))
        if st.button("Load"):
            blog_id = blog_map[selected]
            data = get_blog(blog_id)

            if data:
                title, content = data
                st.session_state["out"] = {
                    "blog_title": title,
                    "final": content
                }

# -----------------------------
# RUN
# -----------------------------
if run_btn and topic:
    st.session_state["running"] = True

    # DEBUG (VERY IMPORTANT)
    st.write(" DEBUG Topic:", topic)

    inputs = {
        "topic": topic.strip(),   #  ensure clean input
        "plan": None,
        "sections": [],
        "final": "",
        "blog_title": "",
        "as_of": date.today().isoformat()
    }

    with st.spinner("Generating blog..."):
        try:
            out = app_graph.invoke(inputs)

            # DEBUG OUTPUT
            st.write(" DEBUG Output:", out)

            st.session_state["out"] = out

        except Exception as e:
            st.error(f"Error: {str(e)}")

    st.session_state["running"] = False

# -----------------------------
# OUTPUT
# -----------------------------
out = st.session_state.get("out")

if out:
    title = out.get("blog_title", "Generated Blog")
    final = out.get("final", "")

    st.subheader("📄 Generated Blog")
    st.title(title)

    st.markdown(final)

    filename = safe_slug(title) + ".md"

    st.download_button(
        "⬇ Download Markdown",
        final,
        file_name=filename
    )

    st.download_button(
        "📦 Download ZIP",
        bundle_zip(final, filename),
        file_name="blog.zip"
    )

    # -----------------------------
    # HASHNODE PUBLISH
    # -----------------------------
    if st.button("🚀 Publish to Hashnode"):
        with st.spinner("Publishing..."):
            try:
                result = publish_to_hashnode(title, final)

                if result and "post_url" in result:
                    st.success("✅ Published Successfully!")
                    st.write(result["post_url"])
                else:
                    st.error("❌ Failed to publish")
                    st.write(result)

            except Exception as e:
                st.error(f"Error: {str(e)}")

else:
    st.info("👈 Enter a topic and click Generate")