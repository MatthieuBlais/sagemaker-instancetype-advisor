import json
from sagemaker import Endpoint
import os

def handler(event, context):
    """Check Sagemaker endpoint status and clean-up if it failed"""

    print(json.dumps(event))

    endpoint = Endpoint(event["EndpointName"], os.environ["AWS_REGION"])
    status = endpoint.status()
    if status == "FAILED":
        endpoint.cleanup()
        raise Exception(f"Endpoint {endpoint.name} failed to create")

    event["EndpointStatus"] = status

    return event