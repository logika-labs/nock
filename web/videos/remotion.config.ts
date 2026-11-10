import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(92);
Config.setEntryPoint("src/index.ts");
Config.setCodec("h264");
Config.setPixelFormat("yuv420p");
