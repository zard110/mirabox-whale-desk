#!/bin/sh
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
dest="$root/presence/models"
mkdir -p "$dest"
scratch=$(mktemp -d "$dest/.fetch.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
base=https://media.githubusercontent.com/media/opencv/opencv_zoo/48b10fa505aeb51fbd127fc60a5c660040e823b7/models
fetch() {
    group=$1
    name=$2
    digest=$3
    if [ -f "$dest/$name" ] && (cd "$dest" && echo "$digest  $name" | sha256sum --check --status); then return; fi
    curl --fail --location --retry 2 --output "$scratch/$name" "$base/$group/$name"
    (cd "$scratch" && echo "$digest  $name" | sha256sum --check)
    mv "$scratch/$name" "$dest/$name"
}
fetch face_detection_yunet face_detection_yunet_2023mar.onnx 8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4
fetch face_recognition_sface face_recognition_sface_2021dec.onnx 0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79
