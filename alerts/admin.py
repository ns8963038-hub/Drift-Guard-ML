from django.contrib import admin
from alerts.models import ThresholdProfile, Alert, RetrainRecommendation

admin.site.register(ThresholdProfile)
admin.site.register(Alert)
admin.site.register(RetrainRecommendation)
