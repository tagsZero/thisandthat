"""Isolated local inference. No network, auto-install or drawing files."""
import gc
import hashlib
import importlib
from io import BytesIO
import json
import os
from pathlib import Path
import pickletools
import platform
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'tmp/khtp-model'
UPSTREAM = WORK / 'upstream/yolov5-d3ea0df8b9f923685ce5f2555c303b8eddbf83fd'
HASHES = {
    'house': 'c65e60d19cf488f5bd8384feb6f8877dffeaf0cd6fc7fd8ca006db4c25727fe3',
    'tree': '89c5a54d667ac390c8a54d4147d22329de8762f65035e88d5f5bad26662d364b',
    'personf': 'cd299f46f6bb9bdb2ba36662fb8f0f9f720dfdd4781e0e8dcedd986ac5ac394b',
    'personm': '3410a14c2de25ad07048215e8edf406aaca160901928d7036fbff8c3d9c7b0d4',
}
NAMES = {
    'house': '집전체 지붕 집벽 문 창문 굴뚝 연기 울타리 길 연못 산 나무 꽃 잔디 태양'.split(),
    'tree': '나무전체 기둥 수관 가지 뿌리 나뭇잎 꽃 열매 그네 새 다람쥐 구름 달 별'.split(),
    'personf': '사람전체 머리 얼굴 눈 코 입 귀 머리카락 목 상체 팔 손 다리 발 단추 주머니 운동화 여자구두'.split(),
    'personm': '사람전체 머리 얼굴 눈 코 입 귀 머리카락 목 상체 팔 손 다리 발 단추 주머니 운동화 남자구두'.split(),
}


def verify_sources():
    archive_path = WORK / 'upstream.zip'
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != 'a2150277136099a063546424469db32dc0a2973b5578f929278c153c893d7cdb':
        raise ValueError('source archive hash mismatch')
    with zipfile.ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            if not entry.is_dir():
                relative = Path(*Path(entry.filename).parts[1:])
                if (UPSTREAM / relative).read_bytes() != archive.read(entry):
                    raise ValueError('source mismatch')


def deny_external(event, args):
    if event in {'socket.connect','socket.connect_ex','subprocess.Popen','os.system'}:
        raise RuntimeError('external operations disabled')


def main():
    raw_image = sys.stdin.buffer.read(80 * 1024 * 1024 + 1)
    if len(raw_image) > 80 * 1024 * 1024:
        raise ValueError('image too large')
    verify_sources()
    os.environ.update(YOLOv5_AUTOINSTALL='false', MPLBACKEND='Agg',
        MPLCONFIGDIR=str(WORK / 'mpl'), YOLOV5_CONFIG_DIR=str(WORK / 'config'))
    platform.uname()
    sys.addaudithook(deny_external)
    sys.path.insert(0, str(UPSTREAM))
    import numpy as np
    import torch
    from PIL import Image
    from utils.augmentations import letterbox
    from utils.general import non_max_suppression, scale_coords
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    image = Image.open(BytesIO(raw_image)).convert('RGB')
    source = np.asarray(image)
    outputs = {}
    for kind, expected in HASHES.items():
        try:
            weight = WORK / (kind+'-best.pt')
            if hashlib.sha256(weight.read_bytes()).hexdigest() != expected:
                raise ValueError('weight hash mismatch')
            with zipfile.ZipFile(weight) as archive:
                payload = archive.read(next(n for n in archive.namelist() if n.endswith('data.pkl')))
            safe = []
            for name in sorted({arg for op,arg,_ in pickletools.genops(payload) if op.name == 'GLOBAL'}):
                module, attr = name.split(' ')
                if not any(module == p or module.startswith(p+'.') for p in ('torch','models.common','models.yolo','collections','__builtin__')):
                    raise ValueError('unexpected pickle global')
                safe.append((getattr(importlib.import_module('builtins' if module == '__builtin__' else module),attr),f'{module}.{attr}'))
            with torch.serialization.safe_globals(safe):
                checkpoint = torch.load(weight,map_location='cpu',weights_only=True)
            model = checkpoint['model'].float().eval()
            if list(model.names) != NAMES[kind]:
                raise ValueError('class order mismatch')
            for module in model.modules():
                if isinstance(module,torch.nn.Upsample) and not hasattr(module,'recompute_scale_factor'):
                    module.recompute_scale_factor = None
            padded,ratio,pad = letterbox(source,(1280,1280),auto=False,stride=int(model.stride.max()))
            tensor = torch.from_numpy(np.ascontiguousarray(padded.transpose(2,0,1))).float()[None] / 255
            with torch.inference_mode():
                prediction = model(tensor)[0]
                if prediction.shape[-1] != len(NAMES[kind])+5 or not torch.isfinite(prediction).all():
                    raise ValueError('invalid prediction')
                detections = non_max_suppression(prediction,conf_thres=.25,iou_thres=.45)[0]
            detections = detections.clone()
            if len(detections):
                scale_coords(tensor.shape[2:],detections[:,:4],source.shape,ratio_pad=(ratio,pad))
                if not torch.isfinite(detections).all():
                    raise ValueError('invalid coordinates')
            outputs[kind] = dict(status='ok',weight_sha256=expected,detections=[dict(xyxy=d[:4].tolist(),
                confidence=d[4].item(),class_id=int(d[5]),label=NAMES[kind][int(d[5])]) for d in detections])
            del checkpoint,model,prediction,detections,tensor
            gc.collect()
        except Exception as error:
            print(f'{kind}: {type(error).__name__}: {error}',file=sys.stderr)
            outputs[kind] = dict(status='failed',weight_sha256=expected,detections=[])
    print(json.dumps(dict(models=outputs,settings=dict(device='cpu',size=1280,confidence=.25,nms=.45),
        source_sha256='a2150277136099a063546424469db32dc0a2973b5578f929278c153c893d7cdb'),ensure_ascii=True))


if __name__ == '__main__':
    main()
