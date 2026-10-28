"use client";

import Image from "next/image";
import { StaticImageData } from "next/image";
import { useTranslations } from "next-intl";
import openSourceIcon from "@public/OpenSource.png";
import trelloIcon from "@public/Trello.png";
import serviceNowIcon from "@public/Servicenow.png";
import zAIIcon from "@public/Z_AI.png";

export interface IconProps {
  size?: number;
  className?: string;
}
export interface LogoIconProps extends IconProps {
  src: string | StaticImageData;
}

export const defaultTailwindCSS = "my-auto flex shrink-0 text-default";
export const defaultTailwindCSSBlue = "my-auto flex shrink-0 text-link";

export const LogoIcon = ({
  size = 16,
  className = defaultTailwindCSS,
  src,
}: LogoIconProps) => {
  const t = useTranslations("common.icons");
  return (
    <Image
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] object-contain ` + className}
      src={src}
      alt={t("logo.alt")}
      width="96"
      height="96"
    />
  );
};

// Helper to create simple icon components from react-icon libraries
export function createIcon(
  IconComponent: React.ComponentType<{ size?: number; className?: string }>
) {
  function IconWrapper({
    size = 16,
    className = defaultTailwindCSS,
  }: IconProps) {
    return <IconComponent size={size} className={className} />;
  }

  IconWrapper.displayName = `Icon(${
    IconComponent.displayName || IconComponent.name || "Component"
  })`;
  return IconWrapper;
}

/**
 * Creates a logo icon component that automatically supports dark mode adaptations.
 *
 * Depending on the options provided, the returned component handles:
 * 1. Light/Dark variants: If both `src` and `darkSrc` are provided, displays the
 *    appropriate image based on the current color theme.
 * 2. Monochromatic inversion: If `monochromatic` is true, applies a CSS color inversion
 *    in dark mode for a monochrome icon appearance.
 * 3. Static icon: If only `src` is provided, renders the image without dark mode adaptation.
 *
 * @param src - The image or SVG source used for the icon (light/default mode).
 * @param options - Optional settings:
 *   - darkSrc: The image or SVG source used specifically for dark mode.
 *   - monochromatic: If true, applies a CSS inversion in dark mode for monochrome logos.
 *   - sizeAdjustment: Number to add to the icon size (e.g., 4 to make icon larger).
 *   - classNameAddition: Additional CSS classes to apply (e.g., '-m-0.5' for margin).
 * @returns A React functional component that accepts {@link IconProps} and renders
 *          the logo with dark mode handling as needed.
 */
const createLogoIcon = (
  src: string | StaticImageData,
  options?: {
    darkSrc?: string | StaticImageData;
    monochromatic?: boolean;
    sizeAdjustment?: number;
    classNameAddition?: string;
  }
) => {
  const {
    darkSrc,
    monochromatic,
    sizeAdjustment = 0,
    classNameAddition = "",
  } = options || {};

  const LogoIconWrapper = ({
    size = 16,
    className = defaultTailwindCSS,
  }: IconProps) => {
    const adjustedSize = size + sizeAdjustment;

    // Build className dynamically (only apply monochromatic if no darkSrc)
    const monochromaticClass = !darkSrc && monochromatic ? "dark:invert" : "";
    const finalClassName = [className, classNameAddition, monochromaticClass]
      .filter(Boolean)
      .join(" ");

    // If darkSrc is provided, use CSS-based dark mode switching
    // This avoids hydration issues and content flashing since next-themes
    // sets the .dark class before React hydrates
    if (darkSrc) {
      return (
        <>
          <LogoIcon
            size={adjustedSize}
            className={`${finalClassName} dark:hidden`}
            src={src}
          />
          <LogoIcon
            size={adjustedSize}
            className={`${finalClassName} hidden dark:block`}
            src={darkSrc}
          />
        </>
      );
    }

    return (
      <LogoIcon size={adjustedSize} className={finalClassName} src={src} />
    );
  };

  LogoIconWrapper.displayName = "LogoIconWrapper";
  return LogoIconWrapper;
};

// ============================================================================
// GENERIC SVG COMPONENTS (sorted alphabetically)
// ============================================================================
export const MacIcon = ({
  size = 16,
  className = "my-auto flex shrink-0 ",
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        d="M6.5 4.5a2 2 0 0 1 2 2v2h-2a2 2 0 1 1 0-4Zm4 4v-2a4 4 0 1 0-4 4h2v3h-2a4 4 0 1 0 4 4v-2h3v2a4 4 0 1 0 4-4h-2v-3h2a4 4 0 1 0-4-4v2h-3Zm0 2h3v3h-3v-3Zm5-2v-2a2 2 0 1 1 2 2h-2Zm0 7h2a2 2 0 1 1-2 2v-2Zm-7 0v2a2 2 0 1 1-2-2h2Z"
      />
    </svg>
  );
};
export const OnyxLogoTypeIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  const aspectRatio = 736 / 159;
  const height = size / aspectRatio;

  return (
    <svg
      version="1.1"
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={height}
      viewBox="0 0 736 159"
      style={{ width: `${size}px`, height: `${height}px` }}
      className={`w-[${size}px] h-[${height}px] ` + className}
    >
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M19.8589 19.8598L0.000656479 72.681L52.8219 52.8228L72.6801 0.00156887L19.8589 19.8598ZM105.69 105.691L85.8317 158.512L138.653 138.654L158.511 85.8326L105.69 105.691ZM85.8324 0L138.654 19.8598L158.514 72.6813L105.692 52.8217L85.8324 0ZM52.8217 105.691L0 85.832L19.8595 138.654L72.6813 158.513L52.8217 105.691Z"
        fill="currentColor"
      />
      <g>
        <path
          d="M219 124.96L242.316 91.378C234.544 89.29 228.86 85.926 225.264 81.286C221.668 76.53 219.87 70.788 219.87 64.06C219.87 54.896 223.234 47.704 229.962 42.484C236.806 37.148 247.652 34.48 262.5 34.48H312.96V124.96H288.6V93.64H268.764L246.84 124.96H219ZM288.6 81.46V46.66H262.5C257.28 46.66 253.22 48.168 250.32 51.184C247.42 54.084 245.97 58.376 245.97 64.06C245.97 69.744 247.42 74.094 250.32 77.11C253.22 80.01 257.28 81.46 262.5 81.46H288.6Z"
          fill="currentColor"
        />
        <path
          d="M384.368 79.198L422.648 124.96H394.808L370.448 95.902L346.088 124.96H318.248L356.528 79.198L319.118 34.48H346.958L370.448 62.668L393.938 34.48H421.778L384.368 79.198Z"
          fill="currentColor"
        />
        <path
          d="M473.21 117.13C476.922 117.13 480.402 116.434 483.65 115.042C486.898 113.65 489.74 111.504 492.176 108.604C494.612 105.588 496.526 101.702 497.918 96.946C499.426 92.19 500.18 86.448 500.18 79.72C500.18 72.992 499.426 67.25 497.918 62.494C496.526 57.738 494.612 53.91 492.176 51.01C489.74 47.994 486.898 45.79 483.65 44.398C480.402 43.006 476.922 42.31 473.21 42.31C469.498 42.31 466.018 43.006 462.77 44.398C459.522 45.79 456.68 47.994 454.244 51.01C451.808 53.91 449.836 57.738 448.328 62.494C446.936 67.25 446.24 72.992 446.24 79.72C446.24 86.448 446.936 92.19 448.328 96.946C449.836 101.702 451.808 105.588 454.244 108.604C456.68 111.504 459.522 113.65 462.77 115.042C466.018 116.434 469.498 117.13 473.21 117.13ZM473.21 31C480.982 31 488.116 32.102 494.612 34.306C501.224 36.394 506.85 39.526 511.49 43.702C516.13 47.762 519.726 52.866 522.278 59.014C524.946 65.046 526.28 71.948 526.28 79.72C526.28 87.608 524.946 94.568 522.278 100.6C519.726 106.632 516.13 111.736 511.49 115.912C506.85 119.972 501.224 123.046 494.612 125.134C488.116 127.338 480.982 128.44 473.21 128.44C465.322 128.44 458.13 127.338 451.634 125.134C445.138 123.046 439.57 119.972 434.93 115.912C430.29 111.736 426.636 106.632 423.968 100.6C421.416 94.568 420.14 87.608 420.14 79.72C420.14 71.948 421.416 65.046 423.968 59.014C426.636 52.866 430.29 47.762 434.93 43.702C439.57 39.526 445.138 36.394 451.634 34.306C458.13 32.102 465.322 31 473.21 31Z"
          fill="currentColor"
        />
        <path
          d="M633.324 34.48V124.96H608.964V84.94H561.984V124.96H537.624V34.48H561.984V72.76H608.964V34.48H633.324Z"
          fill="currentColor"
        />
        <path
          d="M736.059 46.66H699.519V124.96H675.159V46.66H638.619V34.48H736.059V46.66Z"
          fill="currentColor"
        />
      </g>
    </svg>
  );
};
export const WindowsIcon = ({
  size = 16,
  className = "my-auto flex shrink-0 ",
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width="24"
      height="24"
    >
      <path
        fill="currentColor"
        d="M3 3h8v8H3V3zm10 0h8v8h-8V3zm-10 10h8v8H3v-8zm10 0h8v8h-8v-8z"
      />
    </svg>
  );
};

// ============================================================================
// THIRD-PARTY / COMPANY ICONS (Alphabetically)
// Only icons that don't yet have opal logo equivalents remain here.
// ============================================================================
export const OpenSourceIcon = createLogoIcon(openSourceIcon);
export const ServiceNowIcon = createLogoIcon(serviceNowIcon);
export const TrelloIcon = createLogoIcon(trelloIcon);
export const ZAIIcon = createLogoIcon(zAIIcon);
