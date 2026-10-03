FROM rust:1.83-bookworm AS build
WORKDIR /app
COPY Cargo.toml Cargo.lock ./
COPY src ./src
COPY tests ./tests
RUN cargo test --release --locked && cargo build --release --locked

FROM debian:bookworm-slim
RUN groupadd --gid 10001 brain && useradd --uid 10001 --gid brain --no-create-home brain
COPY --from=build /app/target/release/brain-resolver /usr/local/bin/brain-resolver
USER brain
EXPOSE 8082
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["brain-resolver", "--healthcheck"]
ENTRYPOINT ["brain-resolver"]
