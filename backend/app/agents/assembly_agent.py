clips = []
    skipped = []
    errors = []
    for i, (url, dur) in enumerate(zip(urls, durations)):
        img_path = os.path.join(work_dir, f"shot_{i:03d}.jpg")
        if not os.path.exists(img_path):
            ok = _download_image(url, img_path)
            if not ok:
                skipped.append(i)
                errors.append(f"shot {i}: download failed")
                continue
        try:
            clip = _ken_burns_clip(img_path, dur)
            clips.append(clip)
        except Exception as e:
            skipped.append(i)
            errors.append(f"shot {i}: {type(e).__name__}: {str(e)[:150]}")
            continue

    if not clips:
        raise ValueError(f"All shots failed. Errors: {errors}")
