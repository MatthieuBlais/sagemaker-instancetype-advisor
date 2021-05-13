import json
from sagemaker import Endpoint
import os

def handler(event, context):

    print(json.dumps(event))

    endpoint = Endpoint(event["EndpointName"], os.environ["AWS_REGION"])
    endpoint.cleanup()

    return event