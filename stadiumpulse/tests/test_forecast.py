import sys
import os
import unittest

# Ensure backend modules are on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend')))

from forecast.data_generator import generate_zone_scenario
from forecast.forecast_service import forecast_zone

class TestForecastService(unittest.TestCase):
    
    def setUp(self):
        self.capacity = 1000
        self.zone_metadata = {
            "zone_id": "zone_north",
            "zone_name": "North Gate Concourse",
            "connected_gates": ["gate_1", "gate_2"],
            "accessible_routes": ["route_elevator_1"]
        }

    def test_normal_scenario(self):
        """
        Verify that a 'normal' scenario with steady, low counts evaluates to
        'normal' status. Uses a deterministic hand-crafted history at ~35%
        capacity to avoid flakiness from random data generation.
        """
        # Deterministic history: steady around 350 out of 1000 capacity (~35%)
        history = [340, 345, 350, 355, 348, 352, 347, 350, 353, 349]
        
        result = forecast_zone(history, self.capacity, self.zone_metadata)
        
        self.assertEqual(result["zone_id"], "zone_north")
        self.assertEqual(result["capacity"], self.capacity)
        self.assertEqual(result["status"], "normal")
        self.assertLess(result["forecast_count_15min"], self.capacity * 0.70)
        self.assertLess(result["forecast_count_30min"], self.capacity * 0.70)

    def test_spike_scenario(self):
        """
        Verify that a 'spike' scenario shows rising counts that trigger a status
        escalation to 'watch' or 'critical'.
        """
        # Generate 30 minutes of counts simulating a surge to ~90-95% capacity
        series = generate_zone_scenario("zone_north", 30, scenario_type="spike", capacity=self.capacity)
        history = [count for _, count in series]
        
        result = forecast_zone(history, self.capacity, self.zone_metadata)
        
        self.assertEqual(result["zone_id"], "zone_north")
        self.assertEqual(result["capacity"], self.capacity)
        # With our spike profile, at the 30th minute it has surged, so forecast should be >= 70% capacity
        self.assertIn(result["status"], ["watch", "critical"])

    def test_edge_case_empty_history(self):
        """
        Verify that passing an empty list of counts does not crash the service,
        and returns zero values with 'normal' status.
        """
        result = forecast_zone([], self.capacity, self.zone_metadata)
        
        self.assertEqual(result["current_count"], 0)
        self.assertEqual(result["forecast_count_15min"], 0)
        self.assertEqual(result["forecast_count_30min"], 0)
        self.assertEqual(result["status"], "normal")

    def test_edge_case_one_data_point(self):
        """
        Verify that passing only one data point handles the prediction gracefully
        (flat trend) without dividing by zero.
        """
        result = forecast_zone([350], self.capacity, self.zone_metadata)
        
        self.assertEqual(result["current_count"], 350)
        self.assertEqual(result["forecast_count_15min"], 350)
        self.assertEqual(result["forecast_count_30min"], 350)
        self.assertEqual(result["status"], "normal")

if __name__ == '__main__':
    unittest.main()
