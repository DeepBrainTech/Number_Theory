FROM sagemath/sagemath:latest

USER root
WORKDIR /app
COPY server.py /app/server.py
EXPOSE 8011
ENTRYPOINT []
CMD ["sage", "-python", "/app/server.py"]
