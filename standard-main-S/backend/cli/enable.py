"""
enable — EngineeringStudio enableSim CLI
"""
from __future__ import annotations

import sys
import yaml
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

# ympl_parser and the studio adapters both live under studio/. This has to run
# at import time: the --vids branch imports ympl_parser before the function
# below gets a chance to set the path up.
_STUDIO_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _STUDIO_DIR.parent
for p in [_STUDIO_DIR, _REPO_ROOT / 'sdk', _REPO_ROOT / 'sdk' / 'ympl-parser']:
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

app     = typer.Typer(name='enable', add_completion=False,
                      help='EngineeringStudio enableSim tools')
console = Console()


@app.command()
def convert(
    ympl_file: Path = typer.Argument(..., help='Input file (YMPL or VIDS YAML)'),
    vids: bool = typer.Option(
        False, '--vids',
        help='Input is VIDS format (Engineering Studio native)',
    ),
    output: Optional[Path] = typer.Option(
        None, '--out', '-o',
        help='Output path (default: <stem>_ympl.ympl or <stem>_enablesim.ympl)',
    ),
):
    """Convert a VIDS or YMPL file for use with enableSim."""
    if not ympl_file.exists():
        console.print(f'[red]Error:[/red] file not found: {ympl_file}')
        raise typer.Exit(1)

    if vids:
        # ── VIDS → YMPL ────────────────────────────────────────────────────────
        from ympl_parser.io import read_ympl
        from ympl_parser.convert import vids_to_ympl

        doc       = read_ympl(ympl_file)
        converted = vids_to_ympl(doc)

        if output is None:
            output = ympl_file.parent / f'{ympl_file.stem}_ympl.ympl'

        with open(output, 'w', encoding='utf-8') as f:
            yaml.dump(converted, f, default_flow_style=False, allow_unicode=True)

        n_eq   = len(converted['enable']['equipment'])
        n_inst = len(converted['enable']['instruments'])
        n_edge = len(converted['edges'])

        console.print(f'OK  equipment:    {n_eq}')
        console.print(f'OK  instruments:  {n_inst}')
        console.print(f'OK  edges:        {n_edge}')
        console.print(f'OK  written: {output}')
        console.print(f'\nNext: [cyan]enable build {output}[/cyan]')
        return

    # ── YMPL → enableSim enrichment ────────────────────────────────────────────
    from ympl_parser.io import read_ympl
    from adapters.ympl_convert import to_enablesim_ympl

    doc      = read_ympl(ympl_file)
    enriched = to_enablesim_ympl(doc)

    if output is None:
        output = ympl_file.parent / f'{ympl_file.stem}_enablesim.ympl'

    with open(output, 'w', encoding='utf-8') as f:
        yaml.dump(enriched, f, default_flow_style=False, allow_unicode=True)

    n_eq   = len(enriched.get('enable', {}).get('equipment', {}))
    n_inst = len(enriched.get('enable', {}).get('instruments', {}))
    n_edge = len(enriched.get('edges', []))

    console.print(f'OK  equipment:    {n_eq}')
    console.print(f'OK  instruments:  {n_inst}')
    console.print(f'OK  edges:        {n_edge}')
    console.print(f'OK  written: {output}')
    console.print(f'\nNext: [cyan]enable build {output}[/cyan]')


@app.command()
def build(
    ympl_file: Path = typer.Argument(..., help='Enriched YMPL file to validate'),
):
    """Validate enableSim YMPL structure and report block counts."""
    if not ympl_file.exists():
        console.print(f'[red]Error:[/red] file not found: {ympl_file}')
        raise typer.Exit(1)

    from ympl_parser.io import read_ympl
    doc    = read_ympl(ympl_file)
    enable = doc.get('enable', {})
    eq     = enable.get('equipment', {})
    instr  = enable.get('instruments', {})
    conns  = enable.get('connections', {})
    nodes  = doc.get('nodes', [])
    edges  = doc.get('edges', [])

    # Validate topology_ref uniqueness
    refs     = [v.get('topology_ref') for v in eq.values()]
    node_ids = {n['id'] for n in nodes}
    dangling = [r for r in refs if r and r not in node_ids]
    dupes    = [r for r in refs if refs.count(r) > 1 and r is not None]

    console.print(f'[bold]enable build[/bold] {ympl_file.name}')
    console.print(f'  nodes:        {len(nodes)}')
    console.print(f'  edges:        {len(edges)}')
    console.print(f'  equipment:    {len(eq)}')
    console.print(f'  instruments:  {len(instr)}')
    console.print(f'  connections:  {len(conns)}')

    if dangling:
        console.print(f'  [yellow]WARN[/yellow] dangling topology_refs: {dangling}')
    if dupes:
        console.print(f'  [yellow]WARN[/yellow] duplicate topology_refs: {list(set(dupes))}')

    if not dangling and not dupes:
        console.print('[green]OK[/green]  structure valid')
    raise typer.Exit(0)


if __name__ == '__main__':
    app()
