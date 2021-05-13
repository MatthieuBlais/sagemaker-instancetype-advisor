from pricing import SagemakerProducts
from pricing import InstanceFilter
import os
import uuid
import json


LOCATION = os.environ.get("PRICING_LOCATION", "Asia Pacific (Singapore)")

def fetch_instances(event):
    """Fetch SageMaker Instances and filter them to meet event criteria"""
    instances = SagemakerProducts.fetch(LOCATION)
    event_filters = event.get("Filters", {})
    filters = {
        'products': instances,
        'min_vcpu': event_filters.get("MinCPU", 0), 
        'max_vcpu': event_filters.get("MaxCPU", float("inf")), 
        'min_memory': event_filters.get("MinMemory", 0), 
        'max_memory': event_filters.get("MaxCPU", float("inf")),
        'min_gpu': event_filters.get("MinGPU", 0), 
        'max_gpu': event_filters.get("MaxGPU", float("inf")),
        'min_usd': event_filters.get("MinUSD", 0), 
        'max_usd': event_filters.get("MaxUSD", float("inf")),
        'instance_types': event_filters.get("InstanceTypes", []),
        'max_instance_types': event_filters.get("MaxInstances", 5)
    }
    return InstanceFilter.apply(**filters)


def format_endpoints(event, instances):
    """Format test jobs for the few selected instances"""
    jobs = []
    test_id = uuid.uuid1().hex
    counter = 0
    for instance in instances:
        instance_id = instance['instanceName'].replace(".", "")
        endpoint_name = "perf-" + instance_id + "-" + event.get("EndpointName", event["ModelName"])
        output_result_key = "_perftesting/" + test_id + "/" + uuid.uuid1().hex + ".json"
        jobs.append({
            "WaitLimit": (counter + 1)*10,
            "EndpointName": endpoint_name,
            "ModelName": event["ModelName"],
            "VariantName": "ALLVARIANT",
            "InstanceDetails": instance,
            "ResultOutputs": {
                "Bucket": os.environ["PERF_TEST_BUCKET"],
                "Key": output_result_key
            },
            "PerfSettings": format_jobs(event, endpoint_name, output_result_key)
        })
        counter += 1
    return jobs

def format_jobs(event, endpoint_name, output_result_key):
    host = os.environ["SERVING_API_HOST"] + os.environ["SERVING_API_ENDPOINT"]
    jobs = []
    if "Percentiles" not in event:
        percentiles = ",".join(DEFAULT_PERCENTILES)
    else:
        percentiles = ",".join([str(x) for x in event['Percentiles']])
    for settings in event.get("Settings", [{}]):
        users = settings.get("Users", 5)
        spawn_rate = settings.get("SpawnRate", 5)
        test_time = settings.get("TestTime", 300)
        jobs.append({
            "EndpointName": endpoint_name,
            "TestDataset": event["TestDataset"],
            "ResultOutputs": {
                "Bucket": os.environ["PERF_TEST_BUCKET"],
                "Key": output_result_key
            },
            "JobDetails": {
                "ClusterName": os.environ["ECS_CLUSTER_NAME"],
                "TaskDefinition": os.environ["LOCUST_TASK_DEFINITION"],
                "AwsRegion": os.environ["AWS_REGION"],
                "Subnets": os.environ["CLUSTER_SUBNETS"].split(","),
                "TaskName": os.environ["LOCUST_TASK_NAME"],
                "Command": f"python3 driver.py -u {users} -r {spawn_rate} -t {test_time} -H {host} --output-bucket {os.environ['PERF_TEST_BUCKET']} --output-key {output_result_key} --percentiles {percentiles}".split(" ")
            }
        })

    return jobs


from sagemaker import Catalog, CatalogFilter
import json
import os
import boto3

class InstanceTypeAdvisor():

    PREFIX = "typeadvisor"
    DEFAULT_PERCENTILES = ["50", "66","75","80","90","95","99","999"]

    def __init__(self, event, catalog):
        """Format test jobs for the few selected instances"""
        self.advisor_id = uuid.uuid1().hex
        self.jobs = []
        self.job_counter = 0
        for instance in catalog:
            instance_name = instance['instanceName'].replace(".", "")
            endpoint_name = self._format_name(instance_name, event.get("EndpointName", event["ModelName"]))
            advisor_output_key = f"{PREFIX}/{self.advisor_id}/{instance_name}.json"
            self.jobs.append({
                "WaitLimit": self._handle_throttling(self.job_counter),
                "EndpointName": endpoint_name,
                "ModelName": event["ModelName"],
                "VariantName": "ALLVARIANT",
                "InstanceDetails": instance,
                "ResultOutputs": {
                    "Bucket": os.environ["TYPE_ADVISOR_BUCKET"],
                    "Key": advisor_output_key
                },
                "PerfSettings": format_jobs(event, endpoint_name, output_result_key)
            })
            self.job_counter += 1
        return jobs

    def _format_name(self, instance_name, name):
        return f"{self.PREFIX}-{instance_name}-{name}"

    def _handle_throttling(self, counter):
        return (counter + 1)*10
    
    def _format_locust_job(self, locust_job, endpoint_name, output_result_key):
        host = os.environ["SERVING_API_HOST"] + os.environ["SERVING_API_ENDPOINT"]
        jobs = []
        if "Percentiles" not in event:
            percentiles = ",".join(DEFAULT_PERCENTILES)
        else:
            percentiles = ",".join([str(x) for x in event['Percentiles']])
        for settings in event.get("Settings", [{}]):
            jobs.append({
                "EndpointName": endpoint_name,
                "DistributedLocust": {
                    "JobDetails": self._format_job(execution_id, "master", locust_job)
                    "Jobs": [
                        self._format_job(execution_id, "worker", locust_job) for _ in range(locust_job["ExpectedWorkers"])
                    ]
                }   
            })

        return jobs

    def _prepare_locust_job(self, locust_job, shapes_key, output_key):
        if "Percentiles" not in locust_job:
            locust_job["Percentiles"] = DEFAULT_PERCENTILES
        locust_job["OutputKey"] = output_key
        shapes = locust_job["Users"]
        self._upload_json(locust_job["StagingBucket"], shape_key, shapes)
        locust_job["ShapesKey"] = shapes_key
        return locust_job
        

    def _generate_shape(self, users, duration):
        shapes = []
        consec_duration = 0
        for user in users:
            shapes.append({"users": user, "duration": consec_duration + duration, "spawn_rate": user})
        shapes.append({"users": 0, "duration": consec_duration + duration, "spawn_rate": 100 })
        return shapes

    def _upload_json(self, bucket, key, content):
        s3 = boto3.client("s3")
        s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(content))

    def _format_job(self, execution_id, job_type, locust_job):
        task_key = "MasterTaskName" if job_type == "master" else "WorkerTaskName"
        command_key = "MasterCommand" if job_type == "master" else "WorkerCommand"
        return {
            "ExecutionId": execution_id,
            "ClusterName": locust_job["ClusterName"],
            "TaskDefinition": locust_job["TaskDefinition"],
            "AwsRegion": os.environ["AWS_REGION"],
            "Subnets": locust_job["Subnets"],
            "SecurityGroups": locust_job["SecurityGroups"],
            "FamilyName": locust_job["TaskName"],
            task_key: locust_job["TaskName"],
            command_key: self._format_command(locust_job, job_type)
        }

    def _format_command(self, locust_job, command_type):
        command = [
            "python3",
            "app/main.py",
            "--host",
            locust_job["EndpointHost"],
            "--method",
            locust_job["Method"],
            "--client-type",
            command_type,
            "--percentiles",
            ",".join(locust_job["Percentiles"]),
            "--shapes-bucket",
            locust_job["StagingBucket"],
            "--shapes-key",
            locust_job["ShapesKey"],
            "--testdata-bucket",
            locust_job["StagingBucket"],
            "--testdata-key",
            locust_job["TestDataKey"],
            "--output-bucket",
            locust_job["StagingBucket"],
            "--output-key",
            locust_job["OutputKey"]
        ]
        if command_type == "master":
            command += [
                "--expected-workers",
                str(locust_job["ExpectedWorkers"]),
                "--master-host",
                "0.0.0.0"
            ]
        return command



def handler(event, context):
    
    print(json.dumps(event))

    catalog = SageMakerCatalog(
        event["PricingLocation"],
        CatalogFilter(event.get("Filters", {})),
        os.environ.get("PRICING_ENDPOINT", "ap-south-1")
    )

    jobs = format_endpoints(event, instances)

    event["Jobs"] = jobs

    print(json.dumps(event))

    return event


event = {
    "PricingLocation": "Asia Pacific (Singapore)",
    "Filters": {
        "vCPU": { "Min": 0, "Max": 32 },
        "Memory": { "Min": 0, "Max": 32 },
        "GPU": { "Min": 0, "Max": 32 },
        "Price": { "Min": 0, "Max": 32 },
        "Instances": [],
        "Limit": 5
    },
    "AdvisorJob": {
        "ClusterName": "",
        "TaskDefinition": "",
        "Subnets": [],
        "SecurityGroups": [],
        "TaskName": "",
        "Percentiles": "50",
    }
    "PassingCriteria": {
        "RPS": 34,
        "Percentile": "50",
        "OrderBy": "RPS|$" 
    }
}
handler(event, {})

