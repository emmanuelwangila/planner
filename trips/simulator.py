import requests
from datetime import datetime, timedelta
from math import ceil
from decouple import config
import logging

logger = logging.getLogger(__name__)

class TripSimulator:
    def __init__(self, geoapify_token=None, current_cycle_used=0):
        self.geoapify_token = geoapify_token or config('GEOAPIFY_TOKEN', default=None)
        if not self.geoapify_token:
            raise ValueError("Geoapify token is required")
        
        self.remaining_cycle = 70 - current_cycle_used
        self.driving_limit = 11
        self.on_duty_limit = 14
        self.rest_hours = 10
        self.break_hours = 0.5
        self.avg_speed = 55
        self.fuel_time = 0.5
        self.pickup_time = 1
        self.dropoff_time = 1

    def geocode(self, address):
        """Geocode address and return (lat, lon)"""
        url = "https://api.geoapify.com/v1/geocode/search"
        params = {"text": address, "apiKey": self.geoapify_token}
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            features = data.get("features", [])
            if not features:
                raise ValueError(f"No results found for address: {address}")

            # Geoapify returns [lon, lat] - convert to (lat, lon)
            coords = features[0]["geometry"]["coordinates"]
            return (coords[1], coords[0])  # return (lat, lon)
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Geocoding API error for {address}: {e}")
            raise ValueError(f"Geocoding failed: {str(e)}")

    def get_route(self, start_coords, end_coords, waypoints=None):
        """Get route between coordinates using correct Geoapify routing format"""
        # Geoapify routing expects coordinates in lat,lon format (not lon,lat)
        waypoints_list = [
            f"{start_coords[0]},{start_coords[1]}",  # lat,lon of start
            f"{end_coords[0]},{end_coords[1]}"       # lat,lon of end
        ]
        
        # Add intermediate waypoints if any
        if waypoints:
            for wp in waypoints:
                waypoints_list.insert(-1, f"{wp[0]},{wp[1]}")  # Insert before the last point

        # Join waypoints with the correct format
        waypoints_param = "|".join(waypoints_list)

        url = "https://api.geoapify.com/v1/routing"
        params = {
            "waypoints": waypoints_param,
            "mode": "drive",
            "apiKey": self.geoapify_token
        }

        logger.debug(f"Routing request - URL: {url}, waypoints: {waypoints_param}")

        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            logger.debug(f"Routing API response: {data}")
            
            # Check for API errors in response
            if "error" in data or "statusCode" in data:
                error_msg = data.get("message", "Unknown API error")
                logger.error(f"API returned error: {error_msg}")
                raise ValueError(f"Routing API error: {error_msg}")
            
            if not data.get("features"):
                logger.error(f"No route features in response: {data}")
                raise ValueError("No route found for the given locations")

            feature = data["features"][0]
            props = feature["properties"]
            
            # Check if we have valid distance and time
            if "distance" not in props or "time" not in props:
                logger.error(f"Missing distance or time in route properties: {props}")
                raise ValueError("Invalid route response - missing distance or time")
            
            dist_miles = props["distance"] * 0.000621371
            time_hours = props["time"] / 3600

            return {
                "geojson": feature["geometry"],
                "distance": dist_miles,
                "duration": time_hours,
                "fuel_locations": waypoints or []
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Routing API error: {e}")
            raise ValueError(f"Route calculation failed: {str(e)}")
        except KeyError as e:
            logger.error(f"Unexpected API response format: {e}")
            raise ValueError(f"Unexpected response format from routing API")

    def calculate_fuel_stops(self, total_distance):
        """Calculate fuel stops needed (every 1000 miles)"""
        if total_distance <= 1000:
            return 0
        return ceil(total_distance / 1000) - 1

    def create_eld_log_entry(self, status, hours, description, start_time, day_start):
        """Create a standardized ELD log entry"""
        elapsed_hours = (start_time - day_start).total_seconds() / 3600
        return {
            "status": status,
            "hours": hours,
            "description": description,
            "start_time": start_time.isoformat(),
            "elapsed_hours": round(elapsed_hours % 24, 2)
        }

    def simulate_trip_timeline(self, total_driving_hours, total_distance, num_fuel_stops):
        """Simulate the complete trip timeline with ELD compliance"""
        events = []
        daily_logs = []
        
        now = datetime.now()
        current_day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        current_log = {
            "date": current_day_start.date().isoformat(),
            "entries": [],
            "total_driving": 0,
            "total_on_duty": 0
        }
        
        # Simplified simulation for short distances
        driving_remaining = total_driving_hours
        
        # Driving to pickup
        drive_segment = min(driving_remaining, 2.0)
        events.append({
            "type": "drive",
            "hours": drive_segment,
            "note": "Driving to pickup location",
            "start": now.isoformat()
        })
        current_log["entries"].append(self.create_eld_log_entry(
            "D", drive_segment, "Driving to pickup", now, current_day_start
        ))
        driving_remaining -= drive_segment
        now += timedelta(hours=drive_segment)
        
        # Pickup
        events.append({
            "type": "pickup",
            "hours": self.pickup_time,
            "note": "Loading at pickup location",
            "start": now.isoformat()
        })
        current_log["entries"].append(self.create_eld_log_entry(
            "ON", self.pickup_time, "Loading", now, current_day_start
        ))
        now += timedelta(hours=self.pickup_time)
        
        # Main driving
        if driving_remaining > 0:
            events.append({
                "type": "drive",
                "hours": driving_remaining,
                "note": "Main route to destination",
                "start": now.isoformat()
            })
            current_log["entries"].append(self.create_eld_log_entry(
                "D", driving_remaining, "Route driving", now, current_day_start
            ))
            now += timedelta(hours=driving_remaining)
        
        # Dropoff
        events.append({
            "type": "dropoff",
            "hours": self.dropoff_time,
            "note": "Unloading at destination",
            "start": now.isoformat()
        })
        current_log["entries"].append(self.create_eld_log_entry(
            "ON", self.dropoff_time, "Unloading", now, current_day_start
        ))
        
        # Finalize log
        current_log["total_driving"] = total_driving_hours
        current_log["total_on_duty"] = total_driving_hours + self.pickup_time + self.dropoff_time
        daily_logs.append(current_log)
        
        return events, daily_logs

    def simulate(self, current_addr, pickup_addr, dropoff_addr):
        logger.info(f"Starting simulation: {current_addr} -> {pickup_addr} -> {dropoff_addr}")
        
        if self.remaining_cycle < 10:
            raise ValueError("Insufficient cycle hours remaining (minimum 10 required)")

        try:
            # Geocode all addresses
            current_coords = self.geocode(current_addr)
            pickup_coords = self.geocode(pickup_addr)
            dropoff_coords = self.geocode(dropoff_addr)
            
            logger.info(f"Geocoded coordinates: current={current_coords}, pickup={pickup_coords}, dropoff={dropoff_coords}")

            # Calculate routes - for short trips, use direct routing without waypoints
            route_to_pickup = self.get_route(current_coords, pickup_coords)
            logger.info(f"Route to pickup: {route_to_pickup['distance']} miles, {route_to_pickup['duration']} hours")
            
            main_route = self.get_route(pickup_coords, dropoff_coords)
            logger.info(f"Main route: {main_route['distance']} miles, {main_route['duration']} hours")
            
            total_distance = route_to_pickup['distance'] + main_route['distance']
            total_driving_hours = route_to_pickup['duration'] + main_route['duration']
            
            logger.info(f"Total route: {total_distance} miles, {total_driving_hours} hours")

            # Calculate fuel stops
            num_fuel_stops = self.calculate_fuel_stops(total_distance)
            
            # Generate simplified fuel locations
            fuel_locations = []
            if num_fuel_stops > 0:
                for i in range(num_fuel_stops):
                    fraction = (i + 1) / (num_fuel_stops + 1)
                    lat = pickup_coords[0] + fraction * (dropoff_coords[0] - pickup_coords[0])
                    lng = pickup_coords[1] + fraction * (dropoff_coords[1] - pickup_coords[1])
                    fuel_locations.append({
                        "lat": round(lat, 6),
                        "lng": round(lng, 6),
                        "name": f"Fuel Stop {i+1}",
                        "distance_from_start": round((i + 1) * 1000, 1)
                    })
            
            # Simulate timeline
            events, daily_logs = self.simulate_trip_timeline(
                total_driving_hours, total_distance, num_fuel_stops
            )
            
            return {
                'events': events,
                'daily_logs': daily_logs,
                'total_distance': round(total_distance, 1),
                'total_driving_hours': round(total_driving_hours, 1),
                'route_geojson': main_route['geojson'],
                'fuel_stops': num_fuel_stops,
                'fuel_locations': fuel_locations,
                'remaining_cycle_hours': round(self.remaining_cycle - total_driving_hours - self.pickup_time - self.dropoff_time - (num_fuel_stops * self.fuel_time), 1),
                'status': 'success',
                'message': 'Trip simulation completed successfully'
            }
            
        except Exception as e:
            logger.error(f"Simulation error: {str(e)}", exc_info=True)
            raise ValueError(f"Simulation failed: {str(e)}")