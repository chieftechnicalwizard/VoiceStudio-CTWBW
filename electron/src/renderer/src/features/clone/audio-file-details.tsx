import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { readWavInfo, type WavInfo } from '@/lib/audio/wav-info';

export function AudioFileDetails({ blob }: { blob: Blob }) {
  const { t } = useTranslation();
  const [info, setInfo] = useState<{ blob: Blob; wav: WavInfo | null } | null>(null);
  useEffect(() => {
    let active = true;
    void blob
      .slice(0, 65536)
      .arrayBuffer()
      .then((buffer) => {
        if (active) setInfo({ blob, wav: readWavInfo(buffer) });
      })
      .catch(() => {
        if (active) setInfo(null);
      });
    return () => {
      active = false;
    };
  }, [blob]);
  const wav = info?.blob === blob ? info.wav : null;
  const size = (blob.size / 1048576).toFixed(2);
  return (
    <p className="text-xs text-muted-foreground tabular-nums">
      {wav
        ? t('cloneQuality.fileInfo', {
            size,
            rate: wav.sampleRate / 1000,
            channels: wav.channels,
            bits: wav.bits,
            encoding: wav.encoding === 'float' ? t('cloneQuality.float') : 'PCM',
          })
        : t('cloneQuality.fileSize', { size })}
    </p>
  );
}
