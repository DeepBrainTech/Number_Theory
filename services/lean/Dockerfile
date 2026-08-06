FROM ghcr.io/leanprover-community/mathlib4/lean@sha256:6101ecbfd9b1ef7485b49acf1ade33cc1e945188ebe14ea0ff993b0975c8ea40

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git python3 \
    && rm -rf /var/lib/apt/lists/*
RUN git init /mathlib \
    && git -C /mathlib remote add origin https://github.com/leanprover-community/mathlib4.git \
    && git -C /mathlib fetch --depth 1 origin b2418b04047e1da8b7dd99534965d44fc1de9288 \
    && git -C /mathlib checkout --detach FETCH_HEAD \
    && chown -R lean:lean /mathlib
USER lean
ENV HOME=/home/lean
ENV ELAN_HOME=/home/lean/.elan
WORKDIR /mathlib
RUN lake exe cache get
COPY --chown=lean:lean server.py /app/server.py
EXPOSE 8012
ENTRYPOINT []
CMD ["python3", "/app/server.py"]
