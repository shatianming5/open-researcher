"""FastAPI web dashboard for Open Researcher."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from open_researcher.results_cmd import load_results
from open_researcher.status_cmd import parse_research_state

DASHBOARD_DIR = Path(__file__).parent


def create_app(repo_path: Path | None = None) -> FastAPI:
    if repo_path is None:
        repo_path = Path.cwd()

    app = FastAPI(title="Open Researcher Dashboard")

    @app.get("/api/status")
    def api_status():
        return parse_research_state(repo_path)

    @app.get("/api/results")
    def api_results():
        return load_results(repo_path)

    @app.get("/api/docs/{name}")
    def api_doc(name: str):
        allowed = ["project-understanding.md", "evaluation.md", "program.md"]
        if name not in allowed:
            return {"error": "not found"}
        path = repo_path / ".research" / name
        if not path.exists():
            return {"content": ""}
        return {"content": path.read_text()}

    @app.get("/", response_class=HTMLResponse)
    def index():
        template_path = DASHBOARD_DIR / "templates" / "index.html"
        if template_path.exists():
            return template_path.read_text()
        return "<h1>Open Researcher Dashboard</h1><p>Templates not found.</p>"

    return app
