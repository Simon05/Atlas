"""Synthetic scan for browser checks and public screenshots. Never reads user folders."""
import argparse, json, sys, tempfile, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from atlas_scan import scan
from atlas_relations import build_relations


def fixture():
    with tempfile.TemporaryDirectory(prefix='atlas-ui-') as tmp:
        folder = Path(tmp)
        files = {
            'Studio project/package.json': '{"name":"studio","private":true}',
            'Studio project/src/main.js': 'import "../assets/cover.svg";\n' * 5,
            'Studio project/assets/cover.svg': '<svg xmlns="http://www.w3.org/2000/svg"><rect width="100" height="100" fill="tan"/></svg>',
            'Portfolio/assets/cover.svg': '<svg xmlns="http://www.w3.org/2000/svg"><rect width="100" height="100" fill="tan"/></svg>',
            'Portfolio/package.json': '{"name":"portfolio","private":true}',
            'Icons/arrow.svg': '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0L10 10"/></svg>',
            'Brand guide.pdf': '%PDF-1.4\nSynthetic duplicate document\n' * 120,
            'Brand guide copy.pdf': '%PDF-1.4\nSynthetic duplicate document\n' * 120,
            'Moodboard.svg': '<svg xmlns="http://www.w3.org/2000/svg"><circle r="12"/></svg>',
            'Notes.txt': 'A few useful ideas to keep for another day.\n' * 100,
            'Video previews/clip.pek': 'Generated audio preview sample\n' * 500,
        }
        for name, content in files.items():
            p = folder / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        with zipfile.ZipFile(folder / 'Icons.zip', 'w') as archive:
            archive.write(folder / 'Icons/arrow.svg', 'Icons/arrow.svg')
        d = scan(folder)
    # Stable fictional paths/times; never expose a developer's home or installed apps.
    d.update(root='/Example/Downloads', home='/Example', scannedAt=1794700800,
             applications=[])
    for i, r in enumerate(d['records']):
        r['mtime'] = d['scannedAt'] - [7, 80, 240, 500][i % 4] * 86400
    return d


def payload():
    d = fixture()
    return {'scan': d, 'connections': build_relations(d)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--page', type=Path, help='Write a standalone synthetic preview')
    args = parser.parse_args()
    data = payload()
    if args.page:
        safe = lambda obj: json.dumps(obj).replace('<', '\\u003c')
        template = (ROOT / 'app/atlas-template.html').read_text()
        page = template.replace('__SNAPSHOT__', safe(data['scan'])).replace('__CONNECTION_DATA__', safe(data['connections'])).replace('__THUMBNAILS__', '{}')
        args.page.parent.mkdir(parents=True, exist_ok=True)
        args.page.write_text(page)
    else:
        print(json.dumps(data))
