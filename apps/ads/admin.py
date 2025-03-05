from django.contrib import admin
from . import models
# Register your models here.
admin.site.register(models.AdCampaign)
admin.site.register(models.AdAudience)
admin.site.register(models.AdCreative)
admin.site.register(models.AdBudget)
admin.site.register(models.AdAnalytics)
admin.site.register(models.AdImpression)