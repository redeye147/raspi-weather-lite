#!/bin/bash
# HDMI の音声を切る（サイネージは音を使わない）。
# テレビによっては、HDMI の音声の情報を読めないというカーネルのメッセージ
#   hdmi-audio-codec ...: HDMI: audio coding xtype 6 not expected
# が 10 秒ごとに出て、ログ（SD カードへの書き込み）が無駄に増える（2026-10-25 の 112）。
# config.txt の dtoverlay=vc4-kms-v3d（または vc4-fkms-v3d）に ,noaudio を足す。再起動後に有効。
# 使い方: hdmi_noaudio.sh [config.txt のパス]   既に入っていれば何もしない
cfg="${1:-/boot/firmware/config.txt}"
[ -f "$cfg" ] || { echo "  config.txt が見つかりません（$cfg）"; exit 0; }
if ! grep -Eq '^[[:space:]]*dtoverlay=vc4-f?kms-v3d' "$cfg"; then
    echo "  dtoverlay=vc4-kms-v3d の行が無いので、HDMI の音声はそのまま"
    exit 0
fi
if grep -Eq '^[[:space:]]*dtoverlay=vc4-f?kms-v3d[^#]*noaudio' "$cfg"; then
    echo "  HDMI の音声は切ってあります"
    exit 0
fi
sed -i -E 's/^([[:space:]]*dtoverlay=vc4-f?kms-v3d[^[:space:]#]*)/\1,noaudio/' "$cfg"
echo "  HDMI の音声を切りました（config.txt に ,noaudio。再起動後に有効）"
