"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "./ui/button";

type Crop = { x: number; y: number; width: number; height: number };

type Props = {
  onChange: (value: { image: File | null; cropImage: Blob | null; crop: Crop | null; previewUrl: string | null; cropPreviewUrl: string | null }) => void;
};

export default function ImageCropPicker({ onChange }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [cropPreview, setCropPreview] = useState<string | null>(null);
  const [crop, setCrop] = useState<Crop | null>(null);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);

  useEffect(() => {
    if (!file) {
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    setCropPreview((current) => {
      if (current) URL.revokeObjectURL(current);
      return null;
    });
    onChange({ image: file, cropImage: null, crop: null, previewUrl: url, cropPreviewUrl: null });
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const resetImage = () => {
    setFile(null);
    setPreview(null);
    setCropPreview((current) => {
      if (current) URL.revokeObjectURL(current);
      return null;
    });
    setCrop(null);
    setDragStart(null);
    if (inputRef.current) {
      inputRef.current.value = "";
    }
    onChange({ image: null, cropImage: null, crop: null, previewUrl: null, cropPreviewUrl: null });
  };

  const draw = (nextCrop: Crop | null) => {
    const canvas = canvasRef.current;
    const image = imgRef.current;
    if (!canvas || !image) {
      return;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    ctx.drawImage(image, 0, 0);
    if (nextCrop) {
      ctx.strokeStyle = "#22c55e";
      ctx.lineWidth = Math.max(4, image.naturalWidth / 160);
      ctx.strokeRect(nextCrop.x, nextCrop.y, nextCrop.width, nextCrop.height);
    }
  };

  const point = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = event.currentTarget;
    const rect = canvas.getBoundingClientRect();
    const rawX = ((event.clientX - rect.left) / rect.width) * canvas.width;
    const rawY = ((event.clientY - rect.top) / rect.height) * canvas.height;
    return {
      x: Math.max(0, Math.min(canvas.width, rawX)),
      y: Math.max(0, Math.min(canvas.height, rawY)),
    };
  };

  const makeCropBlob = async (nextCrop: Crop) => {
    const image = imgRef.current;
    if (!image || nextCrop.width < 8 || nextCrop.height < 8) {
      setCropPreview((current) => {
        if (current) URL.revokeObjectURL(current);
        return null;
      });
      onChange({ image: file, cropImage: null, crop: null, previewUrl: preview, cropPreviewUrl: null });
      return;
    }
    onChange({ image: file, cropImage: null, crop: nextCrop, previewUrl: preview, cropPreviewUrl: null });
    const output = document.createElement("canvas");
    output.width = Math.round(nextCrop.width);
    output.height = Math.round(nextCrop.height);
    output.getContext("2d")?.drawImage(image, nextCrop.x, nextCrop.y, nextCrop.width, nextCrop.height, 0, 0, output.width, output.height);
    const blob = await new Promise<Blob | null>((resolve) => output.toBlob(resolve, "image/jpeg", 0.9));
    const cropUrl = blob ? URL.createObjectURL(blob) : null;
    setCropPreview((current) => {
      if (current) URL.revokeObjectURL(current);
      return cropUrl;
    });
    onChange({ image: file, cropImage: blob, crop: nextCrop, previewUrl: preview, cropPreviewUrl: cropUrl });
  };

  useEffect(() => {
    if (!dragStart) {
      return;
    }
    const finishDrag = async (event: MouseEvent) => {
      const canvas = canvasRef.current;
      if (!canvas) {
        return;
      }
      const rect = canvas.getBoundingClientRect();
      const current = {
        x: Math.max(0, Math.min(canvas.width, ((event.clientX - rect.left) / rect.width) * canvas.width)),
        y: Math.max(0, Math.min(canvas.height, ((event.clientY - rect.top) / rect.height) * canvas.height)),
      };
      const next = {
        x: Math.min(dragStart.x, current.x),
        y: Math.min(dragStart.y, current.y),
        width: Math.abs(current.x - dragStart.x),
        height: Math.abs(current.y - dragStart.y),
      };
      setDragStart(null);
      setCrop(next);
      draw(next);
      await makeCropBlob(next);
    };
    window.addEventListener("mouseup", finishDrag);
    return () => window.removeEventListener("mouseup", finishDrag);
  }, [dragStart, file, preview]);

  const selectWholeImage = async () => {
    const image = imgRef.current;
    if (!image) {
      return;
    }
    const next = { x: 0, y: 0, width: image.naturalWidth, height: image.naturalHeight };
    setCrop(next);
    draw(next);
    await makeCropBlob(next);
  };

  return (
    <div className="grid gap-3">
      <div className="grid gap-2 rounded-md border border-dashed bg-muted/20 p-4">
        <span className="text-sm font-semibold">식단 이미지</span>
        <span className="text-xs text-muted-foreground">
          원본 이미지는 식단 기록에 저장되고, 드래그로 선택한 영역은 음식 검색 테스트나 이후 이미지 분석에 사용할 수 있습니다.
        </span>
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="block w-full rounded-md border bg-background px-3 py-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-2 file:text-sm file:font-semibold file:text-primary-foreground hover:file:bg-primary/90"
          onChange={(event) => {
            const nextFile = event.target.files?.[0];
            if (nextFile) {
              setFile(nextFile);
              setCrop(null);
            }
          }}
        />
        <div className="grid gap-2 text-sm text-muted-foreground">
          <span>{file ? `선택된 파일: ${file.name}` : "선택된 파일이 없습니다."}</span>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" onClick={selectWholeImage} disabled={!file}>
              이미지 전체 선택
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={resetImage} disabled={!file}>
              이미지 선택 취소
            </Button>
          </div>
        </div>
      </div>
      {preview ? (
        <div className="grid gap-2">
          <img ref={imgRef} src={preview} alt="" className="hidden" onLoad={() => draw(crop)} />
          <canvas
            ref={canvasRef}
            className="cursor-crosshair rounded-md border"
            style={{ maxWidth: "100%", height: "auto" }}
            onMouseDown={(event) => setDragStart(point(event))}
            onMouseMove={(event) => {
              if (!dragStart) return;
              const current = point(event);
              const next = {
                x: Math.min(dragStart.x, current.x),
                y: Math.min(dragStart.y, current.y),
                width: Math.abs(current.x - dragStart.x),
                height: Math.abs(current.y - dragStart.y),
              };
              setCrop(next);
              draw(next);
            }}
          />
          <Button type="button" variant="outline" className="w-fit" onClick={() => {
            setCrop(null);
            setCropPreview((current) => {
              if (current) URL.revokeObjectURL(current);
              return null;
            });
            draw(null);
            onChange({ image: file, cropImage: null, crop: null, previewUrl: preview, cropPreviewUrl: null });
          }}>
            선택 영역 초기화
          </Button>
        </div>
      ) : null}
    </div>
  );
}
