# The session hub (Jam: listening together, docs/30, ADR-080/095). A small Dart program, built here and run from an empty image.
# It uses the same rules package as the app, which is a second named build context, `session`:
#   docker build -f hub/Dockerfile --build-context session=../../packages/encore_session hub
# (the compose file does this for you: `docker compose --profile hub up -d --build`).
FROM dart:stable AS build
COPY --from=session . /src/session
WORKDIR /src/hub
COPY . .
# In the repository the rules package sits at ../../packages; in this build it is next to the hub.
RUN sed -i 's#path: ../../../packages/encore_session#path: ../session#' pubspec.yaml \
 && dart pub get \
 && dart compile exe bin/hub.dart -o /out/hub

FROM scratch
COPY --from=build /runtime/ /
COPY --from=build /out/hub /app/hub
USER 1000:1000
EXPOSE 8703
ENTRYPOINT ["/app/hub"]
