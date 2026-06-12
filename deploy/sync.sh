#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
rsync -av web/template_coverage.html web/deployed_template_data.json ~/public_html/template_coverage/
chmod a+r ~/public_html/template_coverage/template_coverage.html
chmod a+r ~/public_html/template_coverage/deployed_template_data.json
