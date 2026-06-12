#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
rsync -av web/nexp_coverage.html web/nexp_dashboard_data.json web/deployed_template_data.json ~/public_html/dev_nexp_coverage/
chmod a+r ~/public_html/dev_nexp_coverage/nexp_coverage.html
chmod a+r ~/public_html/dev_nexp_coverage/nexp_dashboard_data.json
chmod a+r ~/public_html/dev_nexp_coverage/deployed_template_data.json
