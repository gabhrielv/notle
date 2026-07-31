# Vendors the Worker's Python dependencies into python_modules/.
#
# Why a container instead of running the toolchain directly: the Pyodide build
# that pywrangler downloads (0.27.7) loads pyodide.asm.js, which is CommonJS,
# from an ESM entry point. On Node 20 and above that file's bare require("fs")
# call lands in a scope with no require defined, and the sync dies before it
# starts. Node 18 is the newest runtime where it still loads. Pinning the whole
# repo to Node 18 to accommodate one build step, while the front end runs on 22,
# would be the tail wagging the dog, so the build step gets its own runtime.
#
# Revisit when the toolchain ships a Pyodide build that loads on current Node.
FROM node:18-bookworm

RUN curl -LsSf https://astral.sh/uv/install.sh \
    | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh

# The container runs as the caller's UID so the vendored tree is not left owned
# by root, and that UID has no home directory in this image. One writable home
# for everyone covers it.
#
# Do not point UV_PYTHON_INSTALL_DIR somewhere else: uv fails to query the
# Pyodide interpreter when it lives outside the home-relative default, with a
# ModuleNotFoundError that names no useful cause. Leaving uv's own layout alone
# is what makes this work.
ENV HOME=/home/vendor
RUN mkdir -p /home/vendor && chmod 0777 /home/vendor

# Warm the tool env, the Pyodide interpreter and the wheel cache into the image
# so a real run does not redownload roughly 30MB every time.
RUN mkdir -p /warm/src /warm/web/dist \
    && cd /warm \
    && printf '%s\n' \
        '[project]' \
        'name = "warm"' \
        'version = "0.1.0"' \
        'requires-python = "==3.12.*"' \
        'dependencies = ["fastapi"]' > pyproject.toml \
    && printf '%s' \
        '{"name":"warm","main":"src/entry.py","compatibility_date":"2025-06-01",' \
        '"compatibility_flags":["python_workers"]}' > wrangler.jsonc \
    && echo 'x = 1' > src/entry.py \
    && uvx --from workers-py pywrangler sync \
    && rm -rf /warm \
    && chmod -R 0777 /home/vendor

WORKDIR /repo
ENTRYPOINT ["uvx", "--from", "workers-py", "pywrangler"]
CMD ["sync"]
