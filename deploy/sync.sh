#!/bin/bash
rsync -av template_coverage.html deployed_template_data.json ~/public_html/template_coverage/
chmod a+r ~/public_html/template_coverage/template_coverage.html
chmod a+r ~/public_html/template_coverage/deployed_template_data.json
