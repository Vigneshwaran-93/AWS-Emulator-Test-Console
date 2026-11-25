from . import (bedrock, bedrock_agent, bedrock_runtime, comprehend, dynamodb, iam, lambda_, polly,
               rekognition, s3, sagemaker, secrets, sqs, textract, translate)

ORDER = [s3, dynamodb, sqs, lambda_, iam, secrets,                                   # basic
         bedrock, bedrock_runtime, bedrock_agent, comprehend, translate, textract,   # generative / AI
         rekognition, polly, sagemaker]

SERVICES = [m.SERVICE for m in ORDER]
BY_ID = {s["id"]: s for s in SERVICES}
