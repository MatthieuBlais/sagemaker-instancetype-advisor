


zip -r9 ../instancetypeadvisor.zip . -x \*.git\* -x \*.pyc\* -x \*__pycache__\*

cd ..

aws s3 mv instancetypeadvisor.zip "s3://$1/_lambdas/instancetypeadvisor.zip"
