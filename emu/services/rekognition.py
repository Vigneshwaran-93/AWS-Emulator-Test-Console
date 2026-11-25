from ..common import F, action as A, scenario as S, service, sample_image

IMG = F("image", "Image (PNG/JPG)", type="file", sample="scene", help="Leave empty to use a generated sample picture")
IMG2 = F("image2", "Second image (PNG/JPG)", type="file", sample="scene")
COL = F("collection", "Collection ID", "employees", sync=True)


def labels(c, v):
    r = c("rekognition").detect_labels(Image={"Bytes": v["image"]}, MaxLabels=int(v.num("max", 15)), MinConfidence=float(v.num("min", 60)))
    return {"labels": [(l["Name"], round(l["Confidence"], 1)) for l in r["Labels"]]}


def text(c, v):
    r = c("rekognition").detect_text(Image={"Bytes": v["image"]})
    return {"detections": [(t["DetectedText"], t["Type"], round(t["Confidence"], 1)) for t in r["TextDetections"]]}


def faces(c, v):
    return c("rekognition").detect_faces(Image={"Bytes": v["image"]}, Attributes=["ALL"])


def moderation(c, v):
    return c("rekognition").detect_moderation_labels(Image={"Bytes": v["image"]}, MinConfidence=float(v.num("min", 50)))


def compare(c, v):
    return c("rekognition").compare_faces(SourceImage={"Bytes": v["image"]}, TargetImage={"Bytes": v["image2"]}, SimilarityThreshold=float(v.num("threshold", 80)))


def create_col(c, v):
    return c("rekognition").create_collection(CollectionId=v["collection"])


def list_cols(c, v):
    return c("rekognition").list_collections()


def index(c, v):
    return c("rekognition").index_faces(CollectionId=v["collection"], Image={"Bytes": v["image"]}, ExternalImageId=v["ext_id"], MaxFaces=5)


def search(c, v):
    return c("rekognition").search_faces_by_image(CollectionId=v["collection"], Image={"Bytes": v["image"]}, FaceMatchThreshold=80)


def list_faces(c, v):
    return c("rekognition").list_faces(CollectionId=v["collection"])


def delete_col(c, v):
    return c("rekognition").delete_collection(CollectionId=v["collection"])


def scn_media(c, v, s):
    rk, s3, img = c("rekognition"), c("s3"), v["image"]
    s.run("Create bucket + upload image", lambda: (s3.create_bucket(Bucket=v["bucket"]), s3.put_object(Bucket=v["bucket"], Key="uploads/promo.png", Body=img, ContentType="image/png")), soft=True)
    s.run("Detect labels", lambda: [(l["Name"], round(l["Confidence"], 1)) for l in rk.detect_labels(Image={"Bytes": img}, MaxLabels=10)["Labels"]])
    s.run("Detect text in image", lambda: [t["DetectedText"] for t in rk.detect_text(Image={"Bytes": img})["TextDetections"] if t["Type"] == "LINE"], soft=True)
    s.run("Moderation check", lambda: [m["Name"] for m in rk.detect_moderation_labels(Image={"Bytes": img})["ModerationLabels"]], soft=True)
    s.run("Detect faces", lambda: len(rk.detect_faces(Image={"Bytes": img}, Attributes=["ALL"])["FaceDetails"]), soft=True)
    s.run("Detect labels from S3 object", lambda: len(rk.detect_labels(Image={"S3Object": {"Bucket": v["bucket"], "Name": "uploads/promo.png"}})["Labels"]), soft=True)
    s.run("Create face collection", lambda: rk.create_collection(CollectionId="media-faces"), soft=True)
    s.run("Index faces", lambda: rk.index_faces(CollectionId="media-faces", Image={"Bytes": img}, ExternalImageId="promo-1")["FaceRecords"], soft=True)
    s.run("Search collection by image", lambda: rk.search_faces_by_image(CollectionId="media-faces", Image={"Bytes": img})["FaceMatches"], soft=True)
    if v.flag("cleanup"):
        s.run("Cleanup", lambda: (rk.delete_collection(CollectionId="media-faces"), s3.delete_object(Bucket=v["bucket"], Key="uploads/promo.png"), s3.delete_bucket(Bucket=v["bucket"])), soft=True)


SERVICE = service(
    "rekognition", "Rekognition", "genai", "rekognition", "Computer vision: labels, text, faces, moderation, face collections.",
    ("rekognition", "list_collections", {}),
    [
        A("labels", "Detect labels", "", [IMG, F("max", "Max labels", 15, "number"), F("min", "Min confidence", 60, "number")], labels),
        A("text", "Detect text", "", [IMG], text),
        A("faces", "Detect faces", "", [IMG], faces),
        A("moderation", "Moderation labels", "", [IMG, F("min", "Min confidence", 50, "number")], moderation),
        A("compare", "Compare faces", "", [IMG, IMG2, F("threshold", "Similarity threshold", 80, "number")], compare),
        A("create_col", "Create collection", "", [COL], create_col),
        A("list_cols", "List collections", "", [], list_cols),
        A("index", "Index faces", "", [COL, IMG, F("ext_id", "External image id", "emp-1001")], index),
        A("search", "Search faces by image", "", [COL, IMG], search),
        A("list_faces", "List faces", "", [COL], list_faces),
        A("delete_col", "Delete collection", "", [COL], delete_col),
    ],
    [S("media", "Media upload screening", "Store an image in S3, then label, OCR, moderate and detect faces; index it into a face collection and search.",
       [IMG, F("bucket", "Bucket", "media-uploads"), F("cleanup", "Clean up afterwards", True, "checkbox")], scn_media)],
    "https://docs.aws.amazon.com/rekognition/latest/APIReference/Welcome.html")
