import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

const BOTTOM_THRESHOLD = 48;

interface ScrollNode {
  scrollHeight: number;
  scrollTop: number;
  clientHeight: number;
  scrollTo(options: ScrollToOptions): void;
}

export class StickToBottomController {
  private node: ScrollNode | null = null;
  following = true;

  attach(node: ScrollNode | null): void {
    this.node = node;
  }

  userScrolled(): boolean {
    if (!this.node) return this.following;
    const distance =
      this.node.scrollHeight - this.node.scrollTop - this.node.clientHeight;
    this.following = distance <= BOTTOM_THRESHOLD;
    return this.following;
  }

  contentChanged(): void {
    if (!this.node || !this.following) return;
    this.node.scrollTo({
      top: this.node.scrollHeight,
      behavior: "auto",
    });
  }

  resume(): void {
    if (!this.node) return;
    this.following = true;
    this.node.scrollTo({
      top: this.node.scrollHeight,
      behavior: "smooth",
    });
  }
}

export function useStickToBottom(dependency: unknown) {
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const observerRef = useRef<ResizeObserver | undefined>(undefined);
  const controllerRef = useRef(new StickToBottomController());
  const [following, setFollowing] = useState(true);

  const onScroll = useCallback(() => {
    setFollowing(controllerRef.current.userScrolled());
  }, []);

  const resume = useCallback(() => {
    controllerRef.current.resume();
    setFollowing(true);
  }, []);

  useLayoutEffect(() => {
    const node = containerRef.current;
    controllerRef.current.attach(node);
    controllerRef.current.contentChanged();
  }, [dependency]);

  useEffect(() => {
    const node = containerRef.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    observerRef.current?.disconnect();
    observerRef.current = new ResizeObserver(() => {
      controllerRef.current.contentChanged();
    });
    observerRef.current.observe(node);
    const content = contentRef.current;
    if (content) observerRef.current.observe(content);
    return () => observerRef.current?.disconnect();
  }, []);

  return { containerRef, contentRef, following, onScroll, resume };
}
