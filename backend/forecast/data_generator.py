import datetime
import random
from typing import List, Tuple

def generate_zone_scenario(
    zone_id: str, 
    duration_minutes: int, 
    scenario_type: str = "normal", 
    capacity: int = 1000
) -> List[Tuple[str, int]]:
    """
    Generates a synthetic time series of crowd counts for a stadium zone.
    
    Inputs:
    - zone_id: Unique string identifier for the zone
    - duration_minutes: Number of minutes/data points to generate (one per minute)
    - scenario_type: "normal" or "spike"
    - capacity: Maximum safe capacity of the zone (used to scale the counts)
    
    Returns:
    - List[Tuple[str, int]]: List of (ISO 8601 timestamp string, count integer) tuples
    """
    start_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=duration_minutes)
    series = []
    
    # We will generate synthetic counts using mathematical curves
    # for realism, plus minor random noise.
    for i in range(duration_minutes):
        timestamp = (start_time + datetime.timedelta(minutes=i)).isoformat(timespec='seconds')
        
        if scenario_type == "spike":
            # Simulate a surge/spike in crowd count toward the end of the duration
            # e.g., representing halftime or post-match egress
            # Using a sigmoid or exponential-like growth curve
            progress = i / duration_minutes
            if progress < 0.4:
                # Baseline normal level
                base = 0.25 * capacity
                noise = random.randint(-15, 15)
            elif progress < 0.8:
                # Rapid surge
                surge_progress = (progress - 0.4) / 0.4  # scale to 0-1
                base = 0.25 * capacity + (0.65 * capacity * surge_progress)
                noise = random.randint(-20, 20)
            else:
                # Sustained critical load
                base = 0.90 * capacity + (0.05 * capacity * (progress - 0.8) / 0.2)
                noise = random.randint(-10, 10)
            
            count = max(0, int(base + noise))
            
        else: # "normal"
            # Steady fluctuation around 30-40% of capacity
            base = 0.35 * capacity
            # Simulate a slow sinus fluctuation + noise
            wave = 0.05 * capacity * (1.0 + float(random.choice([-1, 1])) * 0.1)
            noise = random.randint(-25, 25)
            count = max(0, int(base + wave + noise))
            
        series.append((timestamp, count))
        
    return series
