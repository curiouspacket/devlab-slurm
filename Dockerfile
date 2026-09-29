# syntax=docker/dockerfile:1
# code-server 4.117.0, official multi-architecture manifest digest.
FROM codercom/code-server:4.117.0@sha256:e6702766518b961c7e3c41095c129c7c9a82b041578c53326c52fa363a057727
USER root
COPY --chown=coder:coder . /opt/devlab-bootstrap/
RUN bash /opt/devlab-bootstrap/scripts/install-system.sh \
 && mkdir -p /opt/devlab-tools \
 && chown coder:coder /opt/devlab-tools \
 && chmod 755 /opt/devlab-bootstrap/scripts/image-entrypoint.sh
ENV POC_TOOLS_DIR=/opt/devlab-tools
USER coder
RUN bash /opt/devlab-bootstrap/scripts/bootstrap-tools.sh
# Image contents stay outside the persistent /home/coder mount.
WORKDIR /home/coder
EXPOSE 8080
ENTRYPOINT ["/opt/devlab-bootstrap/scripts/image-entrypoint.sh"]
CMD ["--bind-addr", "0.0.0.0:8080", "/home/coder"]
