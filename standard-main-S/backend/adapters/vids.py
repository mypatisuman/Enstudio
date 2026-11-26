import yaml
from adapters.engine import export_vids as _export_vids


def to_yaml_string(internal: dict) -> str:
    """Convert internal model to VIDS YAML string."""
    vids = _export_vids(internal)
    return yaml.dump(vids, default_flow_style=False, allow_unicode=True)
