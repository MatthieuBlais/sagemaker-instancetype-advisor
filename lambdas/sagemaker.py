import boto3
import json
import math

class CatalogFilter():
    """Filters that can be used with the SageMaker Catalog"""

    def __init__(self, filters):
        cpu_filters = filters.get("vCPU", {})
        memory_filters = filters.get("Memory", {})
        gpu_filters = filters.get("GPU", {})
        costs_filters = filters.get("Price", {})
        instances = filters.get("Instances", [])
        self.filters = {
            "vCpu": lambda x: cpu_filters.get("Min", 0) <= x <= cpu_filters.get("Max", float("inf")),
            "memory": lambda x: memory_filters.get("Min", 0) <= x <= cpu_filters.get("Max", float("inf")),
            "gpu": lambda x: gpu_filters.get("Min", 0) <= x <= gpu_filters.get("Max", float("inf")),
            "onDemandUsdPrice": lambda x: costs_filters.get("Min", 0) <= x <= costs_filters.get("Max", float("inf")),
            "instanceName": lambda x: x in instances or len(instances) == 0
        }
        self.limit = filters.get("Limit", 5)

    def apply(self, catalog):
        """Filter instance types to match criteria"""
        out = []
        for product in catalog:
            valid = True
            for key, filtr in self.filters.items():
                valid = valid and filtr(product[key])
            if valid:
                out.append(product)
        out = sorted(out, key=lambda x: x['onDemandUsdPrice'])
        return self.limit_size(out)

    def limit_size(self, catalog):
        """Reduce number of instance types based on distinct vCPU/memory"""
        if len(catalog)<=self.limit:
            return catalog
        mem = {}
        for instance in catalog:
            if (instance['vCpu'], math.ceil(instance['memory'])) not in mem:
                mem[(instance['vCpu'], math.ceil(instance['memory']))] = instance
        out = [val for val in mem.values()]
        if len(out)>self.limit:
            out = sorted(out, key=lambda x: x['onDemandUsdPrice'])
            return out[:self.limit]
        return out

class Catalog:
    """Interface to fetch all instances types from AWS Catalog / Pricing API"""

    SERVICE_CODE = "AmazonSageMaker"

    def __init__(self, location, filters, region_name):
        self.pricing = boto3.client("pricing", region_name=region_name)
        self.location = location
        self.filters = filters

    def fetch(self, compute_type=None):
        """Fetch SageMaker Instance type pricing"""
        has_next_page = True
        next_token = None
        results = []
        while has_next_page:
            params = {
                "ServiceCode": self.SERVICE_CODE,
                "Filters": self._filter(self.location, compute_type=compute_type)
            }
            if next_token:
                params["NextToken"] = next_token
            response = self.pricing.get_products(**params)
            results += self._format(response)
            next_token = response.get("NextToken")
            has_next_page = next_token is not None
        results = self.filters.apply(results)
        return results

    def _filter(self, location, component="Hosting", compute_type=None):
        """Apply filters on pricing catalog to extract only SageMaker data"""
        filters = [
            ["TERM_MATCH", "location", location],
            ["TERM_MATCH", "productFamily", "ML Instance"],
            ["TERM_MATCH", "currentGeneration", "Yes"],
            ["TERM_MATCH", "component", component]
        ]
        if compute_type:
            filters.append(["TERM_MATCH", "computeType", compute_type])
        return [{
            'Type': x[0],
            'Field': x[1],
            'Value': x[2]
        } for x in filters]

    def _format(self, response):
        """Format instance types keeping interesting metadata only"""
        return [{
                "instanceName": x['product']['attributes']["instanceName"],
                "computeType": x['product']['attributes']['computeType'],
                "vCpu": int(x['product']['attributes'].get('vCpu', 0)),
                "memory": float(x['product']['attributes'].get('memory', '0').replace(" GiB", "")),
                "gpu": int(x['product']['attributes'].get('gpu', '0').replace('N/A', '0')),
                "gpuMemory": int(x['product']['attributes'].get('gpuMemory', '0').replace('N/A', '0')),
                "onDemandUsdPrice": self._extract_price(x['terms']['OnDemand']),
        } for x in self._parse_output(response['PriceList'])]

    def _parse_output(self, output):
        """Convert string into JSON"""
        return [json.loads(x) for x in output]

    def _extract_price(self, pricing):
        """Extract OnDemand Pricing"""
        pricing_sku = list(pricing.keys())[0]
        pricing_dimension_key = list(pricing[pricing_sku]["priceDimensions"].keys())[0]
        return float(pricing[pricing_sku]["priceDimensions"][pricing_dimension_key]["pricePerUnit"]["USD"])


class Endpoint():
    """Interface with SageMaker Endpoint"""

    FAILED_STATUS = ["OutOfService", "Failed"]

    def __init__(self, endpoint_name, region_name):
        self.sagemaker = boto3.client("sagemaker", region_name=region_name)
        self.endpoint_name = endpoint_name

    def status(self):
        """Fetch the endpoint details and extract the endpoint status"""
        endpoint = self.sagemaker.describe_endpoint(EndpointName=self.endpoint_name)
        if endpoint["EndpointStatus"] in self.FAILED_STATUS:
            return "FAILED"
        return endpoint["EndpointStatus"]

    def cleanup(self):
        """Delete SageMaker endpoint and its config"""
        self.sagemaker.delete_endpoint(EndpointName=self.endpoint_name)
        self.sagemaker.delete_endpoint_config(EndpointConfigName=self.endpoint_name)
        

