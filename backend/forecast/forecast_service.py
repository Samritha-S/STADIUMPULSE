"""
Forecast Service for StadiumPulse

This service computes near-term crowd density forecasts (15 and 30 minutes)
for a stadium zone using a simple trend extrapolation (Linear Regression)
on the recent count history.

Example Input:
    zone_history = [120, 125, 132, 138, 145]
    capacity = 500
    zone_metadata = {
        "zone_id": "gate_a_concourse",
        "zone_name": "Gate A Concourse",
        "connected_gates": ["gate_a"],
        "accessible_routes": ["route_main_east"]
    }

Example Output:
    {
        "zone_id": "gate_a_concourse",
        "zone_name": "Gate A Concourse",
        "current_count": 145,
        "capacity": 500,
        "forecast_count_15min": 170,
        "forecast_count_30min": 196,
        "status": "normal",
        "connected_gates": ["gate_a"],
        "accessible_routes": ["route_main_east"]
    }
"""

from typing import Dict, Any, List

def forecast_zone(
    zone_history: List[int], 
    capacity: int, 
    zone_metadata: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Computes a crowd flow forecast based on historical count trends.
    Uses simple linear regression on the last N (up to 5) data points
    to extrapolate the crowd count 15 and 30 minutes into the future.
    
    Inputs:
    - zone_history: List of past integers representing crowd counts measured at 1-minute intervals
    - capacity: Maximum safe crowd capacity for the zone
    - zone_metadata: Optional dictionary with zone identifiers and static lists to conform to ZoneState schema
    
    Returns:
    - Dict[str, Any]: A dictionary matching the ZoneState schema exactly.
    """
    if zone_metadata is None:
        zone_metadata = {}

    # Handle edge case: empty or extremely short history
    if not zone_history:
        current_count = 0
        forecast_15 = 0
        forecast_30 = 0
    elif len(zone_history) == 1:
        current_count = zone_history[0]
        forecast_15 = current_count
        forecast_30 = current_count
    else:
        current_count = zone_history[-1]
        
        # Simple Linear Regression over the last N points (default N = 5)
        # to find the slope (growth rate per minute)
        points_to_use = zone_history[-5:]
        n = len(points_to_use)
        
        # x is time index (0 to n-1)
        x_coords = list(range(n))
        y_coords = points_to_use
        
        mean_x = sum(x_coords) / n
        mean_y = sum(y_coords) / n
        
        numerator = sum((x_coords[i] - mean_x) * (y_coords[i] - mean_y) for i in range(n))
        denominator = sum((x_coords[i] - mean_x) ** 2 for i in range(n))
        
        if denominator == 0:
            slope = 0.0
        else:
            slope = numerator / denominator
            
        # Extrapolate 15 and 30 minutes ahead from the last point
        forecast_15 = max(0, int(round(current_count + slope * 15)))
        forecast_30 = max(0, int(round(current_count + slope * 30)))
        
    # Calculate status based on the maximum of the 15-min and 30-min forecasts relative to capacity
    max_forecast = max(forecast_15, forecast_30)
    
    # 70-90% is watch, > 90% is critical, < 70% is normal
    if capacity <= 0:
        ratio = 0.0
    else:
        ratio = max_forecast / capacity
        
    if ratio >= 0.90:
        status = "critical"
    elif ratio >= 0.70:
        status = "watch"
    else:
        status = "normal"
        
    return {
        "zone_id": zone_metadata.get("zone_id", "unknown_zone"),
        "zone_name": zone_metadata.get("zone_name", "Unknown Zone"),
        "current_count": current_count,
        "capacity": capacity,
        "forecast_count_15min": forecast_15,
        "forecast_count_30min": forecast_30,
        "status": status,
        "connected_gates": zone_metadata.get("connected_gates", []),
        "accessible_routes": zone_metadata.get("accessible_routes", [])
    }
