from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.ads.models import AdCampaign, AdAudience, AdBudget
from decimal import Decimal

User = get_user_model()

class AdProximityTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', email='test@example.com', password='password')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        
        # Create a campaign in Santo Domingo (approx 18.48, -69.93)
        self.campaign_sd = AdCampaign.objects.create(
            user=self.user,
            name="Santo Domingo Ad",
            objective="TRAFFIC",
            status="ACTIVE"
        )
        AdAudience.objects.create(
            campaign=self.campaign_sd,
            latitude=18.4861,
            longitude=-69.9312,
            radius=50
        )
        AdBudget.objects.create(
            campaign=self.campaign_sd,
            daily_budget=Decimal('10.00'),
            total_budget=Decimal('100.00')
        )

        # Create a campaign in Santiago (approx 19.45, -70.68), ~130km away
        self.campaign_sti = AdCampaign.objects.create(
            user=self.user,
            name="Santiago Ad",
            objective="TRAFFIC",
            status="ACTIVE"
        )
        AdAudience.objects.create(
            campaign=self.campaign_sti,
            latitude=19.4517,
            longitude=-70.6867,
            radius=50
        )
        AdBudget.objects.create(
            campaign=self.campaign_sti,
            daily_budget=Decimal('10.00'),
            total_budget=Decimal('100.00')
        )

    def test_serve_ads_by_proximity(self):
        # 1. Test from Santo Domingo
        response = self.client.get('/api/ads/campaigns/serve/', {'lat': 18.48, 'lng': -69.93})
        self.assertEqual(response.status_code, 200)
        campaign_names = [c['name'] for c in response.data]
        self.assertIn("Santo Domingo Ad", campaign_names)
        self.assertNotIn("Santiago Ad", campaign_names)

        # 2. Test from Santiago
        response = self.client.get('/api/ads/campaigns/serve/', {'lat': 19.45, 'lng': -70.68})
        self.assertEqual(response.status_code, 200)
        campaign_names = [c['name'] for c in response.data]
        self.assertIn("Santiago Ad", campaign_names)
        self.assertNotIn("Santo Domingo Ad", campaign_names)

        # 3. Test from a middle point (Bonao ~18.94, -70.40)
        # Distance to SD: ~75km (out of 50km radius)
        # Distance to STI: ~60km (out of 50km radius)
        response = self.client.get('/api/ads/campaigns/serve/', {'lat': 18.94, 'lng': -70.40})
        self.assertEqual(response.status_code, 200)
        campaign_names = [c['name'] for c in response.data]
        self.assertNotIn("Santo Domingo Ad", campaign_names)
        self.assertNotIn("Santiago Ad", campaign_names)
        
        # 4. Increase radius of SD campaign to 100km and test from Bonao
        self.campaign_sd.audience.radius = 100
        self.campaign_sd.audience.save()
        
        response = self.client.get('/api/ads/campaigns/serve/', {'lat': 18.94, 'lng': -70.40})
        campaign_names = [c['name'] for c in response.data]
        self.assertIn("Santo Domingo Ad", campaign_names)
