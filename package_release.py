"""Build a portable release archive from an explicit source-only file list."""
import argparse
from pathlib import Path
import zipfile

SOURCE=Path(__file__).resolve().parent
FILES=('image_batch.py','app_setup.py','package_release.py','README.md',
       'config.example.json','requirements.txt','.gitignore','self_test.py',
       'AGENTS.md','docs/AGENT_GUIDE.md','docs/TROUBLESHOOTING.md',
       '.github/workflows/test.yml','web_app.py','web_test.py','web/index.html',
       'web/app.js','web/style.css','Dockerfile','.dockerignore','compose.yaml','docs/WEB_GUIDE.md')


def build_package(destination):
    destination=Path(destination)
    for name in FILES:
        if not name.isascii() or not (SOURCE/name).is_file():
            raise ValueError('Release source file is missing or has a non-ASCII name.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:archive.write(SOURCE/name,'azure-foundry-image-batch/'+name)
    return destination


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Build an ASCII-path, source-only release ZIP.')
    parser.add_argument('--output',default='dist/azure-foundry-image-batch.zip')
    print(build_package(parser.parse_args().output))
