import type { IconProps } from "@opal/types";

const SvgOnyxOctagon = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 159 159"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      fillRule="evenodd"
      clipRule="evenodd"
      d="M19.8589 19.8598L0.000656479 72.681L52.8219 52.8228L72.6801 0.00156887L19.8589 19.8598ZM105.69 105.691L85.8317 158.512L138.653 138.654L158.511 85.8326L105.69 105.691ZM85.8324 0L138.654 19.8598L158.514 72.6813L105.692 52.8217L85.8324 0ZM52.8217 105.691L0 85.832L19.8595 138.654L72.6813 158.513L52.8217 105.691Z"
      fill="currentColor"
    />
  </svg>
);
export default SvgOnyxOctagon;
