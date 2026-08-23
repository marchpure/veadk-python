export type HomeIndicatorProps = {
  floating?: boolean;
  className?: string;
};

const HomeIndicator = ({ floating = true, className }: HomeIndicatorProps) => {
  return (
    <div
      className={[
        'flex justify-center items-end pb-2 w-full h-[34px]',
        floating ? 'absolute bottom-0 inset-x-0 z-50 pointer-events-none' : '',
        className ?? '',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <div className="rounded-full w-36 h-[5px] bg-white mix-blend-difference" />
    </div>
  );
};

export { HomeIndicator };
export default HomeIndicator;