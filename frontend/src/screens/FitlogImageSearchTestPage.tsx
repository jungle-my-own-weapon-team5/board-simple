"use client";

import { useState } from "react";
import * as fitlogApi from "@/api/fitlog";
import ImageCropPicker from "@/components/ImageCropPicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ImageSearchTestResponse } from "@/types";

export default function FitlogImageSearchTestPage() {
  const [image, setImage] = useState<File | null>(null);
  const [cropImage, setCropImage] = useState<Blob | null>(null);
  const [result, setResult] = useState<ImageSearchTestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const search = async () => {
    const query = cropImage ?? image;
    if (!query) {
      setError("Choose an image first");
      return;
    }
    setError(null);
    setResult(await fitlogApi.imageSearchTest(query));
  };

  return (
    <section className="grid gap-5">
      <h1 className="text-3xl font-extrabold">Image search test</h1>
      <Card>
        <CardHeader><CardTitle>Hardcoded image search</CardTitle></CardHeader>
        <CardContent className="grid gap-4">
          <ImageCropPicker onChange={(value) => { setImage(value.image); setCropImage(value.cropImage); }} />
          <Button type="button" className="w-fit" onClick={search}>Search test</Button>
          {error ? <p className="font-semibold text-destructive">{error}</p> : null}
        </CardContent>
      </Card>
      {result ? (
        <Card>
          <CardHeader><CardTitle>{result.mode}</CardTitle></CardHeader>
          <CardContent className="grid gap-2">
            {result.top_k.map((item) => (
              <div key={item.food_name} className="rounded-md border p-3 text-sm">
                <strong>{item.food_name}</strong> · {Math.round(item.similarity * 100)}% · {item.estimated_calories} kcal
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </section>
  );
}
