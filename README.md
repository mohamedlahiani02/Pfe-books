# Prospection forum

    pip install -r requirements.txt
    export PYTHONPATH=src
    python -m prospection --fetch-catalogue      # one page request, only if robots.txt allows
    python -m prospection --limit 5              # trial run
    python -m prospection                        # full run
    pytest

Place a manually saved page at `input/catalogue.html` to avoid any request to the catalogue host.
CSS selectors in `config/config.yaml` (section `parser`) must be validated against the real HTML.

## CI

`.github/workflows/prospection.yml` crawls the catalogue from GitHub runners (`--crawl`), then commits
`data/entreprises.*`, `data/rapport_qualite.md` and a few raw HTML samples (`data/samples/`) to the branch.
Detail-page selectors (`crawl.detail` in the config) are completed from those samples.
