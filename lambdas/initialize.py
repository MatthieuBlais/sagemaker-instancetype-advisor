from sagemaker import Catalog, CatalogFilter
import json
import os
import uuid
import boto3

os.environ["AWS_REGION"] = os.environ.get("AWS_REGION", "ap-southeast-1")

class InstanceTypeAdvisor():

    PREFIX = "typeadvisor"
    DEFAULT_PERCENTILES = ["50", "66","75","80","90","95","99","999"]

    def __init__(self, event, catalog):
        """Format test jobs for the few selected instances"""
        self.advisor_id = uuid.uuid1().hex
        advisor_shapes_key = f"{self.PREFIX}/{self.advisor_id}/shapes.json"
        self._upload_json(event["AdvisorJob"]["StagingBucket"], advisor_shapes_key, event["AdvisorJob"]["Shapes"])
        self.jobs = []
        self.job_counter = 0
        for instance in catalog:
            instance_name = instance['instanceName'].replace(".", "")
            endpoint_name = self._format_name(instance_name, event.get("EndpointName", event["ModelName"]))
            advisor_output_key = f"{self.PREFIX}/{self.advisor_id}/{instance_name}.json"
            self.jobs.append({
                "WaitLimit": self._handle_throttling(self.job_counter),
                "EndpointName": endpoint_name,
                "ModelName": event["ModelName"],
                "VariantName": "ALLVARIANT",
                "InstanceDetails": instance,
                "ResultOutputs": {
                    "Bucket": event["AdvisorJob"]["StagingBucket"],
                    "Key": advisor_output_key
                },
                "DistributedLocust": self._format_advisor_job(event["AdvisorJob"], self.advisor_id + "-" + instance_name, endpoint_name, advisor_output_key, advisor_shapes_key)
            })
            self.job_counter += 1

    def _format_name(self, instance_name, name):
        return f"{self.PREFIX}-{instance_name}-{name}"

    def _handle_throttling(self, counter):
        return (counter + 1)*10
    
    def _format_advisor_job(self, advisor_job, execution_id, endpoint_name, output_result_key, advisor_shapes_key):
        advisor_job = self._prepare_locust_job(advisor_job, advisor_shapes_key, output_result_key)
        return  {
            "JobDetails": self._format_job(execution_id, "master", advisor_job),
            "Jobs": [
                self._format_job(execution_id, "worker", advisor_job) for _ in range(advisor_job["ExpectedWorkers"])
            ]
        }   

    def _prepare_locust_job(self, advisor_job, shapes_key, output_key):
        if "Percentiles" not in advisor_job:
            advisor_job["Percentiles"] = self.DEFAULT_PERCENTILES
        advisor_job["OutputKey"] = output_key
        advisor_job["ShapesKey"] = shapes_key
        return advisor_job

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

    catalog = Catalog(
        event["AdvisorJob"]["PricingLocation"],
        CatalogFilter(event.get("Filters", {})),
        os.environ.get("PRICING_ENDPOINT", "ap-south-1")
    ).fetch()

    advisor = InstanceTypeAdvisor(event, catalog)
    event["Jobs"] = advisor.jobs

    print(json.dumps(event, indent=4))

    return event


# event = {
#     "EndpointName": "myendpoint",
#     "ModelName": "mymodel",
#     "Filters": {
#         "vCPU": { "Min": 0, "Max": 32 },
#         "Memory": { "Min": 0, "Max": 32 },
#         "GPU": { "Min": 0, "Max": 32 },
#         "Price": { "Min": 0, "Max": 32 },
#         "Instances": [],
#         "Limit": 5
#     },
#     "AdvisorJob": {
#         "ClusterName": "",
#         "TaskDefinition": "",
#         "Subnets": [],
#         "SecurityGroups": [],
#         "TaskName": "",
#         "Percentiles": ["50"],
#         "PricingLocation": "Asia Pacific (Singapore)",
#         "StagingBucket": "mlops-configs-20210509172522",
#         "ExpectedWorkers": 1,
#         "Shapes": [{"Users": 45, "Duration": 21}],
#         "EndpointHost": "",
#         "Method": "/hello",
#         "TestDataKey": "sss"
#     },
#     "PassingCriteria": {
#         "RPS": 34,
#         "Percentile": "50",
#         "OrderBy": "RPS|$" 
#     }
# }
# handler(event, {})

