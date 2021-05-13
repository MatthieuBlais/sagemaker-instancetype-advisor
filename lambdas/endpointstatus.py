import json
from sagemaker import Endpoint
import os

def handler(event, context):

    print(json.dumps(event))

    endpoint = Endpoint(event["EndpointName"], os.environ["AWS_REGION"])
    status = endpointendpoint.status()
    if status == "FAILED":
        endpoint.cleanup()
        raise Exception(f"Endpoint {endpoint.name} failed to create")

    event["EndpointStatus"] = status

    return event