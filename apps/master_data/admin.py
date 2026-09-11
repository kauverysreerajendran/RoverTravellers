# Intentionally empty.
#
# The legacy master_data models are no longer exposed in Django admin
# (/admin/master_data/ is gone) or in the sidebar. They remain as models
# because the Forming, Heat Treatment, Finishing and Finished Goods stages
# still reference them (Machine, Employee, Shift, ReasonCode, Location,
# Rack/Shelf/Tray, MaterialMaster, ProductMaster) until those stages move
# onto their own masters, the way Rolling did.
#
# Current master data for Rolling lives in apps.masters instead.
