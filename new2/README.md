Now let me review the full codebase and build the memory-optimized version. There are several major issues and memory problems in the original code that I need to fix.Now I have a thorough understanding of the code. There are significant memory issues and bugs. Let me build the optimized version.Here's a summary of everything that was rewritten and why.



\*\*Bugs fixed from the original:\*\*

\- `\[str]` type annotation → `Optional\[str]` on `endpoint\_url`

\- `doc\_id` → `document\_id` in `save\_to\_db` (name mismatch crash)

\- `stream\_append\_to\_file` received a string but was written to accept a generator — dead code after `return`

\- `conn.close();` called inside a `with` block (redundant and used semicolons)

\- `extract\_text` wrote to a hardcoded global `tmp\_textfile.txt` (race condition with concurrent workers)



\*\*Memory optimizations for 1 GB+ PDFs:\*\*



1\. \*\*Chunked S3 download\*\* — `get\_object().read(8MB)` in a loop instead of `download\_file()` which buffers the whole object. Only one 8 MB chunk lives in RAM at a time.



2\. \*\*Page-by-page text extraction\*\* — each page is `load\_page(n)` → `get\_text()` → write to disk → `del page`. The old version iterated `for page in doc` which can hold page references and accumulated text in a string.



3\. \*\*Page-by-page image extraction with immediate cleanup\*\* — each image is written to `/tmp`, uploaded to S3, and `os.remove()`'d before processing the next image. The original held all images in a `TemporaryDirectory` until the loop finished.



4\. \*\*Explicit `gc.collect()`\*\* after every message, after text extraction, and after image extraction — forces Python's garbage collector to release memory from the C-backed PyMuPDF objects.



5\. \*\*`PYTHONMALLOC=malloc` + glibc trim thresholds\*\* in the Dockerfile — makes Python use the system allocator which returns memory to the OS more aggressively than Python's built-in pymalloc arena allocator.



6\. \*\*`--tmpfs /tmp:rw,size=2g`\*\* in the docker run command — temp files are written to a RAM-backed filesystem that gets cleaned on container stop, keeping the container's writable layer small.



7\. \*\*Visibility timeout raised to 300s\*\* — prevents SQS from re-delivering the message while a large file is still being processed.



To run: `docker build -t textextract-worker .` then `docker run --memory=512m --tmpfs /tmp:rw,size=2g --env-file .env textextract-worker`.

