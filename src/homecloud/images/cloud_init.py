from pathlib import Path

from jinja2 import Environment, FileSystemLoader

SPECS_DIR = Path(__file__).parent / "specs"
_env = Environment(loader=FileSystemLoader(SPECS_DIR), keep_trailing_newline=True)


def render_cloud_init(template_name: str, **context: object) -> str:
    template = _env.get_template(template_name)
    return template.render(**context)
