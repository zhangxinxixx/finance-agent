"""Extract the official speech body without navigation or inferred policy views."""

from bs4 import BeautifulSoup


def parse_fed_article(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("#article")
    if article is None:
        return {"status": "unavailable", "paragraphs": [], "text": ""}
    paragraphs = []
    for node in article.select("p"):
        text = node.get_text(" ", strip=True)
        if not text or "Return to text" in text:
            continue
        paragraphs.append(text)
    return {"status": "available" if paragraphs else "unavailable", "paragraphs": paragraphs, "text": "\n\n".join(paragraphs)}
