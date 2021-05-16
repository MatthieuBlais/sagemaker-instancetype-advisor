## Deploying infrastructure-as-code

The assumption being made is that you already have a SageMaker model ready to be tested.

### Cloudformation

All resources are defined and created using CloudFormation. There are two stacks to deploy:

1. (Optional) Create Fargate cluster: Checkout [this repository](https://github.com/MatthieuBlais/cloud-distributed-locust) to create your Fargate cluster if you don't have
2. api.yaml: To create an API gateway on top of a SageMaker endpoint
3. advisor.yaml: To deploy the orchestration flow (Step Function) starting master node and worker nodes for instance type advisor.
4. (Optional) Create Fargate task definition: Checkout [this repository](https://github.com/MatthieuBlais/cloud-distributed-locust) to create a sample task definition for Locust with Fargate.


### Deployment

1. Deploy api.yaml to create an API Gateway and lambda function that will be used to call the SageMaker endpoint. Replace the placeholder by your own variables.

```
aws cloudformation deploy \
    --template-file api.yaml \
    --stack-name YOUR_STACK_NAME \
    --parameter-overrides apiName=instance-advisor- \
    --capabilities CAPABILITY_NAMED_IAM
```

Make sure it is correctly deployed.

```
aws cloudformation describe-stack-resources \
    --stack-name YOUR_STACK_NAME
```


2. Package and upload your lambda code. Go to the lambdas folder and run the bash command.

```
cd ../lambdas
/bin/bash package.sh YOUR_BUCKET_NAME
```

3. Create the application using the last template.

```
aws cloudformation deploy \
    --template-file advisor.yaml \
    --stack-name instancetype-advisor \
    --parameter-overrides stagingBucket=mlops-configs-20210509172522 \
    --capabilities CAPABILITY_NAMED_IAM
```