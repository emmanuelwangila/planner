from rest_framework.response import Response
from rest_framework.decorators import api_view
from rest_framework import status
import logging
import json
from .simulator import TripSimulator

logger = logging.getLogger(__name__)

@api_view(['POST'])
def simulate_trip(request):
    try:
        data = request.data
        
        # Log the incoming request for debugging
        logger.info(f"Received trip simulation request: {json.dumps(data)}")
        
        # Validate required fields
        required_fields = ['current_location', 'pickup_location', 'dropoff_location']
        for field in required_fields:
            if field not in data:
                logger.warning(f"Missing required field: {field}")
                return Response(
                    {'error': f'Missing required field: {field}', 'type': 'validation_error'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Safely parse current_cycle_used
        try:
            current_cycle_used = int(data.get('current_cycle_used', 0))
        except (ValueError, TypeError):
            current_cycle_used = 0

        # Initialize simulator
        sim = TripSimulator(
            geoapify_token=data.get('geoapify_token'),
            current_cycle_used=current_cycle_used
        )
        
        # Run simulation
        result = sim.simulate(
            data['current_location'],
            data['pickup_location'],
            data['dropoff_location']
        )
        
        logger.info(f"Simulation completed successfully: {result.get('total_distance', 'N/A')} miles")
        return Response(result)
        
    except ValueError as e:
        logger.error(f"Validation error in simulation: {str(e)}")
        return Response(
            {'error': str(e), 'type': 'validation_error'},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.error(f"Unexpected error in simulation: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Internal server error', 'details': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
