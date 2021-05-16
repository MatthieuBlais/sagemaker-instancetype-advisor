import json
import os
import boto3

class InstanceTypeAdvisorResult():
    """Interface to analyze the load testing results"""

    def __init__(self, jobs, settings):
        self.jobs = jobs
        self.s3 = boto3.client('s3', region_name=os.environ["AWS_REGION"])
        self.percentiles = settings['Percentiles']

    def fetch_outputs(self):
        """Read outputs from Locust jobs and summarize them"""
        outputs = []
        for job in self.jobs:
            results = self._read_s3_json(job["ResultOutputs"]["Bucket"], job["ResultOutputs"]["Key"])
            summary = self._summarize_rps(results[0]['history'])
            outputs.append({
                "InstanceDetails": job["InstanceDetails"],
                "Results": summary
            })
        return outputs

    def recommend(self, outputs, criteria):
        """Filter Locust jobs passing the validation criteria"""
        recommendations = []
        for output in outputs:
            datapoint = self._get_recommendation_datapoint(output["Results"], criteria["Users"])
            if datapoint is not None and datapoint[f'p{criteria["Percentile"]}']['avg'] <= criteria["ResponseTime"]:
                recommendations.append({
                    "InstanceDetails": output["InstanceDetails"],
                    "Datapoint": datapoint
                })
        return self._sort_recommendations(recommendations, criteria["Percentile"], criteria.get("OrderBy"))

    def _summarize_rps(self, history):
        """Summarize Locust job results by aggregating history raw data points"""
        mem = {}
        for datapoint in history:
            if datapoint['user_count'] not in mem:
                mem[datapoint['user_count']] = {
                    'user_count': datapoint['user_count'],
                    'average_rps': 0,
                    'average_fps': 0,
                    'count': 0
                }
                self._extract_percentiles(mem[datapoint['user_count']], None, True)
            mem[datapoint['user_count']]['count'] += 1
            mem[datapoint['user_count']]['average_rps'] += datapoint['current_rps']
            mem[datapoint['user_count']]['average_fps'] += datapoint['current_fail_per_sec']
            self._extract_percentiles(mem[datapoint['user_count']], datapoint)
        return sorted(list(self._average_summary(mem).values()), key=lambda x: x['user_count'])

    def _extract_percentiles(self, summarized_data, datapoint, init=False):
        """Extract response times based on percentiles"""
        if init:
            for percentile in self.percentiles:
                summarized_data[f'p{percentile}'] = {
                    "min": float('inf'),
                    "max": float('-inf'),
                    "avg": 0
                }
            return summarized_data
        for percentile in self.percentiles:
            summarized_data[f'p{percentile}'] = {
                "min": min(summarized_data[f'p{percentile}']['min'], datapoint[f'response_time_percentile_{percentile}']),
                "max": max(summarized_data[f'p{percentile}']['max'], datapoint[f'response_time_percentile_{percentile}']),
                "avg": summarized_data[f'p{percentile}']['avg'] + datapoint[f'response_time_percentile_{percentile}']
            }
        return summarized_data

    def _average_summary(self, summary):
        """Apply average function on aggregated data"""
        for users in summary:
            summary[users]['average_rps'] = round(summary[users]['average_rps']/summary[users]['count'], 2)
            summary[users]['average_fps'] = round(summary[users]['average_fps']/summary[users]['count'], 2)
            for percentile in self.percentiles:
                summary[users][f'p{percentile}']['avg'] = round(summary[users][f'p{percentile}']['avg']/summary[users]['count'], 2)
        return summary

    def _get_recommendation_datapoint(self, history, users):
        """Extract data points for a specific user count from the summary data"""
        for datapoint in history:
            if datapoint['user_count'] == users:
                return datapoint
        return None

    def _sort_recommendations(self, recommendations, percentile, sort_by):
        """Sort recommendation based on response time (faster response time first) or costs (cheaper first)"""
        if sort_by == "ResponseTime":
            return sorted(recommendations, key=lambda x: x["Datapoint"][f'p{percentile}']["avg"])
        else:
            return sorted(recommendations, key=lambda x: x["InstanceDetails"]["onDemandUsdPrice"])

    def _read_s3_json(self, bucket, key):
        obj = self.s3.get_object(Bucket=bucket, Key=key)
        return json.loads(obj['Body'].read())

def handler(event, context):
    """Analyze results of load testing and filter instance types that passe the minimum requirements"""

    print(json.dumps(event))

    advisor = InstanceTypeAdvisorResult(event["Jobs"], event['AdvisorJob'])
    outputs = advisor.fetch_outputs()
    recommendations = advisor.recommend(outputs, event["PassingCriteria"])

    output_event = {
        "Recommendations": recommendations,
        "History": outputs
    }

    print(json.dumps(output_event))

    return output_event
