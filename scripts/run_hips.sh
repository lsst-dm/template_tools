#!/bin/bash
# EDIT THESE
DMNUM=DM-53920
REPO=main
RELEASE_ID=w_2026_36
SOURCE=prompt_template
TRACTS='1448,1449,1450,1321,1322,1323'

# Edit if needed
BASE_URI=/sdf/data/rubin/shared/hips_views
INCOLLECTION=u/$USER/LSSTCam/templates/candidates/$DMNUM/$RELEASE_ID,LSSTCam/defaults
HIPS_BASE=u/$USER/LSSTCam/HiPS/candidates/$DMNUM/$RELEASE_ID
PIPELINE=$TEMPLATE_TOOLS_DIR/pipelines/LSSTCam/MakeHips.yaml
BPS_SUBMIT_YAML=$TEMPLATE_TOOLS_DIR/bps/bps_template_curation.yaml

# Modify the TASKS based on which bands have coadds
U_BAND=makeSingleBandRGBCoaddU,makeHighOrderHipsU,makeLowOrderHipsU,writeAllSkyHipsInfoU
G_BAND=makeSingleBandRGBCoaddG,makeHighOrderHipsG,makeLowOrderHipsG,writeAllSkyHipsInfoG
R_BAND=makeSingleBandRGBCoaddR,makeHighOrderHipsR,makeLowOrderHipsR,writeAllSkyHipsInfoR
I_BAND=makeSingleBandRGBCoaddI,makeHighOrderHipsI,makeLowOrderHipsI,writeAllSkyHipsInfoI
Z_BAND=makeSingleBandRGBCoaddZ,makeHighOrderHipsZ,makeLowOrderHipsZ,writeAllSkyHipsInfoZ
Y_BAND=makeSingleBandRGBCoaddY,makeHighOrderHipsY,makeLowOrderHipsY,writeAllSkyHipsInfoY
TASKS=$U_BAND,$G_BAND,$R_BAND,$I_BAND,$Z_BAND,$Y_BAND

# Edit if needed
HIPS_COLLECTION=$HIPS_BASE
HIPS_URI=$BASE_URI/$HIPS_COLLECTION
HIPS_TITLE="$SOURCE $RELEASE_ID"
WHERE="instrument='LSSTCam' AND skymap='lsst_cells_v2' AND tract IN ($TRACTS)"

echo Starting HIPS maps $HIPS_COLLECTION

bps submit $BPS_SUBMIT_YAML -b $REPO -i $INCOLLECTION -o $HIPS_COLLECTION -p "$PIPELINE#$TASKS" -d "$WHERE" \
--extra-qgraph-options \
"-c parameters:base_uri='$HIPS_URI'\
 -c parameters:hips_title='$HIPS_TITLE'"
